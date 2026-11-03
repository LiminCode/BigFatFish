# PR 报告：灵动岛「今日用量」分 Windows / WSL 两个账号显示（2026-11-02）

> **基线**：`d630e7c9`（Merge PR #13，会话小鱼跨重启）
> **分支**：`claude/zen-dubinsky-a7c263`　**日期**：2026-11-02
> **范围**：16 个文件（实现 7、测试 5、文档 4）
> **关联**：[`PR-REPORT-SESSION-CARD-METRO-2026-10-28.md`](PR-REPORT-SESSION-CARD-METRO-2026-10-28.md)（仪表盘与「今日用量」的上一轮）、
> [`PR-REPORT-MEMORY-DISTILL-PHASE1-2026-10-31.md`](PR-REPORT-MEMORY-DISTILL-PHASE1-2026-10-31.md)（同样读 `~/.claude/projects`，WSL 那条路径的来历）、
> 模板 [`PR-REPORT-TEMPLATE.md`](PR-REPORT-TEMPLATE.md)

## 一、核心特性

岛上信息槽的「今日用量」原来只加 Windows 本机 `~/.claude/projects` 下的对话记录，WSL 发行版里跑的
Claude Code（另一个账号，家目录在发行版里）根本看不见——模块文档里明写「只统计本机」。这一轮把
两个账号**分开各显各的**：岛上写 `今日 Win 2.41M · WSL 1.80M`，悬停说明一个账号一行；点数字弹出的
近 7 天仪表盘里，用量与发出的消息两张磁贴也按账号分：大数字 `Win 2.41M · WSL 1.80M`，每天并排两根
柱（■ 实心 Win / □ 空心 WSL），副标题是 7 天合计 + 图例。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 一只表跨多个根 | `UsageMeter(roots=[…])` / `WeekMeter(roots=[…])`：几个 `projects` 目录合成一个账号（几个发行版 / 几个用户都算 WSL） |
| 2 | 两个账号各一只表 | `UsageAccounts` / `WeekAccounts`：本机 + WSL 各出一份 `UsageTotals` / 7 天；`AccountUsage` / `AccountWeek` 带账号键与短名（i18n `usage.account.<键>`） |
| 3 | WSL 根的发现 | `wsl_projects_roots`：注册表里的发行版 × `wsl.exe --list --running --quiet` 在跑的 × `\\wsl.localhost\<发行版>\home\<用户>\.claude\projects` 存在的。没装 WSL → `None`（一个账号、文案照旧）；装了读不到 → `[]`（`WSL --`） |
| 4 | 容错 | 发行版没在运行**不去碰共享**（碰一下就会把它拉起来）；共享刚起来还没就绪时 `WinError 3` → 这一分钟 `--`、下一分钟再试；今天已经读到的数不因为中途读不到而丢（`reachable` 标志 + 还有记录就继续报） |
| 5 | 岛文案 | `claude_usage.headline / detail`：一个账号 `今日 2.38M`（和从前一字不差）；两个 `今日 Win 2.38M · WSL 1.10M`，悬停两行 |
| 6 | 仪表盘分账号 | `build_tiles` 对账号列表：`Bar.parts` 每天并排几根、`Tile.value` 两段、副标题带 ■ □ 图例、读不到写 `--`；`MetricTile.part_rects` + `_paint_grouped`（实心 / 1.5px 空心）；大数字一行写不下自动缩字号 34→20px |
| 7 | 枚举更省 | `transcript_files`：`os.scandir` 一层拿 mtime（目录项自带、不另 stat），子代理目录只看窗口内动过的会话下面的，不再全盘 `glob` |

**红线 / 不变量**：
- 没有 WSL 的机器**一个字都不变**：岛文案 `今日 2.38M`、悬停一行、仪表盘一个数一根柱（单账号走原路径，旧断言原样通过）。
- 口径不变：用量 = 输入 + 输出 + 缓存写入；缓存读取单列不计；`(message.id, requestId)` 去重、字段取最大；按本机时区自然日。
- UI 线程不读文件：统计仍在 `ClaudeUsageMonitor` / `UsageDashboard` 的 daemon 线程里，在途只有一次。
- 不新增配置键（无需走 `SETTINGS-CHANGE-GATES.md`）；`usage_changed(str, str)` 信号与 `DynamicIsland.set_usage_info` 接口不变。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/claude_usage.py` | +213 / −22 | `UsageMeter` 多根（`roots`，`reachable`）；新 `transcript_files`（scandir 枚举 + 子代理只看动过的会话）；新 `wsl_share` / `running_distros` / `wsl_projects_roots`（WSL 根的发现与「不碰没在跑的」）；新 `AccountUsage` / `UsageAccounts` 与 `headline` / `detail` 文案拼装；模块文档补两账号与实测 |
| `pet/claude_week.py` | +50 / −20 | `WeekMeter` 多根、改用 `transcript_files`（删掉自己那份 `glob`）；新 `AccountWeek` / `WeekAccounts`（根的发现与 `UsageAccounts` 同一套） |
| `pet/claude_usage_monitor.py` | +12 / −7 | 默认统计改 `UsageAccounts().refresh()`；`_on_measured` 接受账号列表（也仍接受一份 `UsageTotals`，当本机那个账号——conftest 里的替身就是这么给的），文案走 `headline` / `detail` |
| `pet/usage_dashboard.py` | +64 / −13 | `DashboardData.usage` 改为 `list[AccountWeek]`；`Bar.parts`；`_tokens_tile` / `_prompts_tile` 单账号走原路径、多账号走新 `_accounts_tile`（大数字两段、7 天合计 + ■ □ 图例、每天并排、读不到写 `--`）；控制器默认统计改 `WeekAccounts` |
| `pet/usage_dashboard_ui.py` | +56 / −3 | `MetricTile.part_rects`（并排几根的矩形，测试也用）、`_paint_grouped`（第一根实心、第二根起 1.5px 空心、没有的贴底细线）；`_value_font` 大数字写不下逐级缩字号 |
| `pet/locale/zh.json` | +14 / −2 | 新键 `usage.account.windows/wsl`、`usage.none`、`usage.headline.multi`、`usage.account_item`、`usage.detail.account/unavailable`、`dashboard.accounts.*`；改 `dashboard.footer`（两个账号各算各的 + 图例）与设置页信息槽说明 |
| `pet/locale/en.json` | +14 / −2 | 同上的英文 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_claude_usage.py` | +77 / −1 | 一只表跨两个根；两个账号分开计数与文案（`今日 Win 1.0K · WSL 305`、两行明细）；没有 WSL 文案照旧；WSL 读不到 → `--` → 恢复 → 再读不到仍保留当天数；`wsl_projects_roots` 按在跑的发行版 × 用户目录找根、没在跑不碰、没装 → `None`；`running_distros` 解析（含 UTF-16 残渣） |
| `tests/test_claude_usage_monitor.py` | +16 / −1 | monitor 下发两账号文案；只给一份 `UsageTotals` 仍当本机账号 |
| `tests/test_claude_week.py` | +18 / −1 | `WeekAccounts` 两账号各自的 7 天（同一串日子）、读不到为 `None`、没 WSL 只一个账号 |
| `tests/test_usage_dashboard.py` | +56 / −2 | 分账号磁贴的大数字 / 副标题图例 / `parts` / 悬停文字；读不到写 `--` 不写 0；`MetricTile.part_rects` 并排、同峰值、无用量高 0、单账号为空；既有用例的 `_usage()` 包成单账号 |
| `tests/test_island_info_slot.py` | +12 / −1 | 两账号文案经 monitor 信号到岛：`今日 Win 2.38M · WSL --`，悬停最后三行 = Win 明细 / WSL 读不到 / 仪表盘提示 |

### 文档

| 文件 | 改动 |
|---|---|
| `docs/PR-REPORT-ISLAND-USAGE-TWO-ACCOUNTS-2026-11-02.md` | 新增（本文） |
| `docs/INDEX.md` | +1 行：PR 报告存档登记 |
| `README.md` / `README.zh-CN.md` | 功能清单一条：两账号并排、仪表盘按账号分；已知限制那条从「不含 WSL」改成「只读在运行的发行版、没开着显示 `WSL --`」 |

### 未改动（故意）

- `pet/dynamic_island.py`：信息槽接口 `set_usage_info(text, detail)` 没动，文案由 monitor 拼好送进来；Metro 磁贴宽度本来就按文字量（`text_w + 16`）。
- `pet/app.py`：接线不变（`usage_changed → island.set_usage_info`）。
- `pet/host_icons.py`：任务书里提到可以用 PowerShell / wsl.exe 图标做两枚小胶囊。没做：岛上那块只有 28px 高，两枚 16px 图标加数字比 `Win` / `WSL` 三个字母更挤、更难一眼看出是谁；文字版已经满足「一眼看出两个账号各用了多少」。要换图标版，`headline` 是唯一要改的拼装点。
- `pet/memory_distill_service.py` 的 `wsl_claude_dir`（`wslpath -w`）没复用：它每次起 wsl.exe **在发行版里**跑命令，发行版没在跑会把它拉起来；这里要的恰恰是「没在跑就别碰」。

## 三、实现要点

**账号 = 一组根 + 一只表。** 账号键只有两个：`windows`（本机 `home/.claude/projects`）和 `wsl`（在运行的每个发行版、每个
`home/<用户>/.claude/projects`，合成一只表）。表是增量的、按 `(message.id, requestId)` 去重，不同根之间 id 不会撞（不同账号）；
同一账号几个根合成一只表也只是把文件列表并起来。`UsageAccounts.refresh()`：先本机，再问一次 `wsl_roots()`，`None` 直接返回
一个账号；否则把根塞进 WSL 那只表刷新；`not reachable and messages == 0` 才报 `None`（显示 `--`），有过当天记录就继续报上一次的数。

**为什么先问 `wsl.exe --list --running`。** `\\wsl.localhost\<发行版>` 的 9P 文件服务跑在发行版的 init 里；发行版没在运行时访问共享会
把它启动起来。桌宠一分钟读一次，不该替用户开发行版，也不该让它永远关不掉。一个 `--quiet` 子进程 50–160 ms、`CREATE_NO_WINDOW`
（复用 `claude_hooks.run_wsl`，`WSL_UTF8=1`），代价可接受。`root` 的家目录共享上是拒绝访问（实测 `Access denied`），所以只看 `home/*`。

**枚举为什么换 `os.scandir`。** 原来 `Path.glob("*/*.jsonl")` 再逐个 `stat()`，本机上无所谓；UNC 上每次 `stat` 是一次 9P 往返，
`*/*/subagents/*.jsonl` 还要钻进每个会话目录。`os.scandir` 的目录项在 Windows 上自带 mtime（`entry.stat()` 不发系统调用），子代理目录
只在「这个会话今天动过」时才看——子代理跑完结果总会写回父对话，父文件就被碰了；跨零点的长子代理最多晚几分钟被计入。
实测 WSL 侧一遍 2725 ms → 1102 ms（§四）。两只表（今日 / 7 天）共用这一个函数。

**文案拼装放在纯模块里。** `headline` / `detail` 在 `claude_usage`（零 Qt），monitor 只是调用；一个账号时返回 `UsageTotals.headline/detail`
原字符串，所以旧断言、旧截图全部不变。仪表盘同理：`_single_account()` 为真走原来的 `_count_bars`，否则 `_accounts_tile`。

**线程模型不变。** 读文件、起 wsl.exe、走共享都在既有的 daemon 线程里；在途只有一次（`_busy`），换代作废（`_generation`）。UNC 卡住
（发行版启动中）只会让那一次测量晚回来，下一分钟不叠加。

## 四、性能分析

**方法（可复现）**：`.venv\Scripts\python.exe -c "...pet.claude_usage..."`（见下表的函数名；脚本在会话草稿目录，逻辑就是
直接调这些函数计时）。环境：Windows 11 Pro 26300、Python 3.13.15、PySide6；WSL 2 `Ubuntu-24.04` 正在运行；
WSL 侧 `~/.claude/projects` 有 1009 个项目目录、1214 个目录项、114 个 jsonl、今天动过 14 个（108.9 MB）；本机今天 4 个文件（67.5 MB）。
样本：每项 3 次取典型值（UNC 波动 ±10%）。**必须从 PowerShell 起 Python**：Git Bash 沙箱里起的 Python 访问 `\\wsl.localhost` 报
`WinError 3`（同一路径、同一解释器）。

| 指标 | 实测 | 归属 |
|---|---|---|
| `running_distros()`（一个 `wsl.exe --list --running --quiet` 子进程） | 52–156 ms，典型 103 ms | 新增，每次刷新 1 次 |
| `wsl_projects_roots()`（含上一项 + `home` 列目录 + `is_dir`） | 118 ms | 新增，每次刷新 1 次 |
| 本机枚举：新 `transcript_files` vs 旧 `glob`+`stat` | 1 ms vs 5 ms | 既有路径，变快 |
| WSL 枚举：新 `transcript_files` vs 旧 `glob`+`stat`（1009 个目录） | **1102 ms vs 2725 ms** | 新增路径（旧法只是对照） |
| 共享读吞吐（今天 14 个文件 115 MB 顺序读） | 1157 ms（≈100 MB/s） | 新增，仅首次 / 有追加时 |
| `UsageAccounts.refresh()` #1（本机 67.5 MB + WSL 108.9 MB 首读） | 2415 ms | 首次 |
| `UsageAccounts.refresh()` #2 / #3（没有新内容，0 字节读） | 1350 / 1285 ms | **稳态，每分钟 1 次** |
| `WeekAccounts.refresh()` #1（本机 94 MB + WSL 156 MB，7 天） | 3292 ms（渲染脚本里一次 4045 ms） | 仪表盘首开 |
| `WeekAccounts.refresh()` #2 / #3 | 1719 / 1484 ms | 仪表盘开着时每分钟 1 次 |
| 只有本机、没有 WSL 的机器 | 与改前同级（本机枚举 1 ms，无子进程） | 既有 |

**结论**：
1. **稳态开销**：岛显示用量时，worker 线程每分钟从原来的约 2 ms 变成约 1.3 s，全部花在 WSL 侧——`wsl.exe` 约 0.1 s、9P 上 1009 次
   目录读约 1.1 s、打开 14 个文件查长度几十毫秒；0 字节解析。UI 线程不参与（I/O 期间 GIL 释放）；实机重启后日志里没有新的慢帧告警
   归属于这条路径。没有 WSL 的机器稳态不变。
2. **新增路径成本与触发频率**：首次约 2.4 s（读 176 MB）、之后每分钟约 1.3 s，只在「岛开着 + 信息槽选了今日用量」时发生；仪表盘只在
   打开期间每分钟一次（首开 3.3–4 s，状态栏显示「正在读对话记录…」）。
3. **新的系统调用 / 网络 / 磁盘 / 线程**：每次刷新多一个无窗口 `wsl.exe` 子进程、一串 `\\wsl.localhost` 的 9P 目录读与文件读
   （走 WSL 虚拟机的 vsock，不出网）；**没有新线程**（沿用各自的 daemon 线程）。发行版没在运行时只有那个子进程，不碰共享。
4. **内存**：多一只表：WSL 当天去重后的回复键（几百到几千个元组）+ 14 个文件偏移；7 天那只是几千条；都是 KB 级。本机那只表原样。

**可再省的地方（没做，记为后续）**：1009 次目录读是因为「哪个文件今天动过」要看文件 mtime；按项目目录 mtime 缓存子列表、
只对已知 jsonl 做 stat，可把稳态压到 100–200 ms，但要处理 `--resume` 追加旧文件不改目录 mtime 的情况。当前 1.3 s/分钟的后台 I/O
先按可接受交付。

## 五、实机运行记录

**前提复现（改前的盲区）**：本机同时有两边今天的对话。WSL 侧经共享能数到今天 14 个 jsonl / 108.9 MB，改前的 `UsageMeter()` 只看本机
（4 个文件），岛上的数字只有 Win 那份。

**一次性坑（UNC）**，都在代码里容错了：
- PowerShell 的 `Get-ChildItem '\\wsl.localhost\...\*\*.jsonl'` 枚举一遍 **50.9 s**（它逐项取属性）；Python `os.scandir` 同一棵树 1.1 s——
  性能数字一律以 Python 为准。
- 刚用 `wsl.exe -l` 碰过发行版后的几秒内，`os.scandir(共享路径)` 报 `FileNotFoundError: [WinError 3]`，几秒后自愈 → `wsl_projects_roots`
  对 `OSError` 一律按「这一分钟读不到」处理，显示 `--`、下一分钟再试。
- `\\wsl.localhost\<发行版>\root\.claude\projects`：`Access to the path is denied` → 只找 `home\*`。
- `os.listdir('\\\\wsl.localhost\\')` 报 `OSError(22, 用户名或密码不正确)`——不能靠列共享根来发现发行版，所以发行版名来自注册表
  （`vscode_workspaces.wsl_distros`），在不在跑问 `wsl.exe`。

**统计结果（PowerShell 起 Python，直接调新代码）**：

```
running_distros ['Ubuntu-24.04'] 103 ms
wsl_projects_roots [WindowsPath('//wsl.localhost/Ubuntu-24.04/home/<用户>/.claude/projects')] 118 ms
local transcript_files (new): 4 1 ms      local glob (old): 4 5 ms
wsl transcript_files (new): 14 True 1102 ms bytes 108877618
wsl glob (old): 14 2725 ms
refresh #1: 2415 ms | 今日 Win 2.39M · WSL 1.80M | local bytes 67538816 wsl bytes 108877618
refresh #2: 1350 ms | 今日 Win 2.39M · WSL 1.80M | local bytes 67538816 wsl bytes 108877618
refresh #3: 1285 ms | 今日 Win 2.39M · WSL 1.80M | local bytes 67538816 wsl bytes 108877618
Win：2.39M（输出 630.8K · 输入 8.2K · 缓存写入 1.75M；另有缓存读取 127M，不计入）
WSL：1.80M（输出 177.2K · 输入 348 · 缓存写入 1.62M；另有缓存读取 34.4M，不计入）
```

**桌宠重启（真实桌面，`QT_QPA_PLATFORM` 默认 windows）**：结束命令行含 `-m pet` 且不含 `--settings` 的 `BigFish.exe`，
从本工作区目录 `Start-Process BigFish.exe -ArgumentList '-m','pet'`，等 25 s。日志 `%APPDATA%\big-fat-fish\pet-<pid>.log`
里 grep `用量|usage|Traceback|ERROR` 只有一条与本改动无关的 TTS 预缓存跳过。用 `EnumWindows` 找到岛的窗口（656×55 物理像素）
按窗口矩形截图：胶囊上显示 **`今日 Win 2.41M · WSL 1.80M`**（右边照旧是 `2 工作中 · 19 休息中` 与四个图标），Metro 磁贴随文字加宽，
没有被截断。截图在会话草稿目录（含桌面其他内容，不入库）。

**仪表盘（真实窗口渲染，非离屏）**：用真实 Windows 平台插件起 `UsageDashboardWindow`，灌 `WeekAccounts().refresh()` 的实时数据，
`grab()` 存图，深浅两套主题都看了：

```
WeekAccounts.refresh: 4045 ms
用量 | Win 2.41M · WSL 1.80M | 7 天 ■ Win 7.75M · □ WSL 9.03M
  today tip: 11/2 一：Win 2.41M（输出 640.4K） · WSL 1.80M（输出 177.2K）
发出的消息 | Win 16 · WSL 23 | 7 天 ■ Win 99 · □ WSL 156
  today tip: 11/2 一：Win 发出 16 条 · WSL 发出 23 条
```

图上：两张磁贴大数字一行放下（缩到 28px），每天两根柱实心 / 空心并排、同一峰值，副标题 ■ □ 图例与底部口径说明的图例对得上；
上下班 / 专注两张磁贴不受影响。悬停两行明细与「点数字看仪表盘」由 `test_island_info_slot` 钉住，没有在真机上再截一次。

**没有自动验证的部分**：发行版**完全没在运行**时的 `WSL --` 分支（用户的发行版里正跑着另一边的 Claude Code，不能 `wsl --shutdown`
去试）——由 `test_an_unreachable_wsl_shows_dashes_then_recovers_and_keeps_todays_numbers` 与 `wsl_projects_roots(running=[])` 的用例覆盖，
并在真机上见过它的近亲（共享刚起来时的 `WinError 3`，见上）。

**测试**：`ruff check pet/ tests/` 通过；相关族（`test_claude_usage` / `test_claude_usage_monitor` / `test_claude_week` /
`test_usage_dashboard` / `test_island_info_slot` / `test_i18n`）87 项连续 3 遍全绿（3.7 s / 遍）；全量 `pytest -q` 见 PR 描述
（本机 4 个与改动无关的基线失败：路径超 260、cp1252 子进程解码 ×2、多显示器负原点）。
