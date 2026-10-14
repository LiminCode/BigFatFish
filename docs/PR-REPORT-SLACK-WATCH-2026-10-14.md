# PR 报告：Slack 关注——电脑在用时每 15 分钟让 WSL 里的 Claude Code 看一眼 Slack，有需要我管的就冒气泡（2026-10-14）

> **基线**：`82f9f7d`（feat(island): 通知中心，`feature/claude-session-fish`）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-14
> **范围**：12 个文件（实现 8：新增 3、改 5；测试 2：新增 1、改 1；文档 2）
> **关联**：[`PR-REPORT-WORK-BRIEFING-2026-10-12.md`](PR-REPORT-WORK-BRIEFING-2026-10-12.md)（同一条通道、同一套只读红线、同一个窗口）、
> [`PR-REPORT-NOTIFICATION-CENTER-2026-10-14.md`](PR-REPORT-NOTIFICATION-CENTER-2026-10-14.md)（同一天做的另一半：Windows 通知中心里的 Slack 通知）

## 一、核心特性

**问题**：通知中心那一半只能看到 Windows 弹过的 toast——没弹过的（Slack 没在前台时的线程回复、被静音频道里的
@、没开通知的私信）看不到，也判断不了「哪条真的在等我」。而工作账号的 Slack 连接器挂在 WSL 里登录的 Claude
Code 上，桌宠自己读不到。

**做了什么**：电脑在用的时候，每 15 分钟（可设 5–240）在 WSL 里无界面跑一次 `claude -p`，让那个账号经 Slack 连接器
只读地看「上次检查之后到现在」有没有**需要我回复或处理**的消息（@我、私信、我参与的线程、明确等我行动的；机器人
告警、纯通知、已有人处理的不算），返回约定的 JSON。桌宠只拿结果：上次没提醒过的条目才冒一个带按钮的提醒气泡
（「查看」开窗口看全文、「知道了」收起），什么新的都没有就安静。右键「Agent 联动 → Slack 关注」：查看最近一次 /
现在检查 / 电脑在用时自动检查（开关）/ 检查间隔。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 人在才跑 | `session_active`：输入桌面是 `Default`（锁屏 / 安全桌面时 `OpenInputDesktop` 打不开或名字是 `Winlogon`）**且**最近 `idle_minutes`（默认 10）分钟内动过键鼠（`GetLastInputInfo`）。锁着、离开、睡着都不跑。 |
| 2 | 节奏 | 每分钟看一眼该不该查：开着、人在、距上次尝试够一个间隔；连着失败 3 次改为一小时一次。启动后约一分钟才第一次看。 |
| 3 | 看的范围 | 上次成功检查之后到现在；第一次看最近 1 小时；太久没查最多看 1 天。 |
| 4 | 只读 | 内置工具 `--tools ''` 整个关掉；只放行简报名单里 Slack 的 8 个读取 / 搜索类工具（`allowed_tools` 从简报的名单里按 `slack` 过滤）；写入类点名拒绝（沿用简报的 `denied_tools`）。 |
| 5 | 约定的 JSON | `{"summary": ≤40 字一句, "items": [{title, from, link, urgency}], "error": ""}`；允许模型包代码围栏或前后说话（取第一个 `{` 到最后一个 `}`）；链接只认 `https://`；最多 8 条。 |
| 6 | 只报新的 | 每条一个键（链接，没有就「来源｜标题」）；状态文件里记着提醒过的键，下次结果里还在的继续记、不在的忘掉；只有新键才冒气泡。 |
| 7 | 气泡与窗口 | 提醒气泡：正文是模型的 `summary`（空则「Slack 上有 N 条需要你看的」），副标题「Slack · N 条需要你看（有急的）」，有 `high` 的优先级提到 1；窗口复用 `WorkBriefingWindow`（标题、按钮文案、空态文字改成可配）。 |
| 8 | 失败不吵 | 自动检查失败只记在状态文件（窗口底部能看到）；手动「现在检查」失败才冒一句。 |

**红线 / 不变量**：
- Slack 内容只在数据目录的 `slack-watch.json`（最近一次结果 + 提醒过的键）里；不进聊天上下文、不送语音合成、不写日志（日志只记成败、用时、条数）。
- 模型手里没有任何能改东西的工具；工具名单是简报名单的子集。
- 默认**关**（`enabled: False`），和简报一样要用户自己打开；菜单只在装了 WSL、宿主接了服务时出现。
- 工作简报的一切行为不变（窗口构造函数只是多了带默认值的关键字参数）。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/slack_watch.py`（新） | +300 | 不碰 Qt 的那一层：`normalize`；`input_desktop_name` / `idle_seconds` / `session_active`；`is_due` / `since_for`；`allowed_tools` / `claude_command` / `build_prompt`；`WatchResult`（`markdown` 属性给窗口）；`parse_output`（JSON 约定、错误分支）；`generate`（一次 wsl.exe）；`load_state` / `record`（失败计数、提醒过的键）/ `fresh_items` / `latest`。 |
| `pet/slack_watch_service.py`（新） | +130 | `SlackWatchService(QObject)`：每分钟 `check`（人在 + 到点）、`check_now`、daemon 线程跑 `generate`、`_done` 回 GUI 落盘并算出新条目、`finished(result, manual, fresh)`。`active` 可注入。 |
| `pet/slack_watch_ui.py`（新） | +90 | `SlackWatchController`：手动动作的即时回话、结果 → 提醒气泡（只对新条目）/ 手动时的一句话、窗口（复用简报窗口）。 |
| `pet/work_briefing_ui.py` | +6 / −4 | `WorkBriefingWindow.__init__` 多 `title` / `regenerate_label` / `empty_text` / `busy_text` 关键字参数（默认值 = 原文案）；空态 / 忙态文字改用实例属性。 |
| `pet/app.py` | +20 | `_start_slack_watch`（和 `_start_work_briefing` 同一处调用、同一套守卫），控制器挂在壳上 `slack_watch`。 |
| `pet/sprite_menu_facade.py` | +33 | 菜单用的 5 个方法：`slack_watch_settings`、`toggle_slack_watch`、`set_slack_watch_interval`、`open_slack_watch`、`check_slack_now`。 |
| `pet/context_menus/shared.py` | +29 | `add_slack_watch_menu`（照 `add_work_briefing_menu`），挂在「Agent 联动」里简报的下面。 |
| `pet/config.py` | +6 | 顶层键 `slack_watch`：默认值、`reload()` 白名单、归一化、`set()` 触发归一化。 |
| `pet/settings_slack_watch.py`（新，第二轮） | +97 | 设置页「Slack 关注」一节：开关 / 间隔 / 离开判定 / 模型（下拉 + 自定义框）；`save_slack_watch_settings`。 |
| `pet/modern_settings_dialog.py`（第二轮） | +2 / −1 | 插节 1 行、保存 1 行，import 并进既有一行。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_slack_watch.py`（新） | +245 | 默认关 + 脏值清理；只在开着且人在时跑、间隔、失败退避；看的范围；`session_active` 四种情况 + 探测出错按不在算；只放行 Slack 读取工具、命令形态；提示词带时间窗；JSON → 条目与键、围栏 / 闲话、四种失败；`generate` 经 stdin 送提示词 + 计时 + 没 WSL；`record` 只报新条目、键随结果走、失败不抹上一次；服务：到点才查、闲置不查、手动不看人在不在；控制器：新条目冒带按钮的气泡并能开窗口、同一批第二次安静、失败只在手动时说、窗口空态。 |
| `tests/test_config_schema.py` | +1 | 白名单快照加 `slack_watch`。 |
| `tests/test_settings_slack_watch.py`（新，第二轮） | +95 | 设置页一节：落在哪个域、显示已存值、保存经归一化、自定义模型、没 WSL 置灰。 |
| `tests/test_architecture.py`（第二轮） | +3 / −1 | 设置页行数预算 2401 → 2403。 |

### 未改动

- `pet/work_briefing.py`：一行没动，`slack_watch.py` 只 import 它的 `normalize_model` / `_sq` / `denied_tools` / `allowed_tools` / `_result_record` / `WslRunner`。
- 没有把结果并进灵动岛的「通知」折叠框：那个框的来源是 Windows 通知中心，这里是模型判断；两边语义不同，先各走各的。

## 三、实现要点

- **判断「人在」为什么用输入桌面名而不是 WTS 锁屏消息**：`session_watcher` 已经在收 `WTS_SESSION_LOCK/UNLOCK`，但它是关机闸门的一部分、只转发「挂起中」给动画降档，没有可查询的锁屏状态；而每分钟一次 `OpenInputDesktop` + `GetUserObjectInformationW` 实测 0.04 ms，直接问系统更简单、也不依赖消息有没有丢。
- **线程与信号**：和简报服务同款——`QTimer` 每分钟在 GUI 线程判断，真查时 daemon 线程跑 wsl.exe，`_done` 信号排队回 GUI，轮次号作废停表后的晚到结果。
- **去重的记忆跟着结果走**：提醒过的键只保留「这次结果里还在的」+「这次新冒的」，最多 200 个；模型哪天把一条旧的又列出来（它还在等你），因为键还记着不会再吵；真的处理完它就不再出现在结果里，键也随之忘掉。
- **取舍**：`summary` 让模型写 ≤40 字，但只截到 120、不硬裁（实测它给了 63 字）；提醒气泡能放下。没做「锁屏回来立刻补查」——下一分钟的检查自然会跑。

## 第二轮：设置页一节（同日）

用户要求频率、方式等都能在设置里改。设置页「自动化与联动」新一节「Slack 关注」（`pet/settings_slack_watch.py`，
排在「通知中心」后面）：

| 行 | 控件 | 说明 |
|---|---|---|
| 电脑在用时自动检查 | 开关 | 没装 WSL 时置灰并说明原因，保存时保持关 |
| 检查间隔 | 5–240 分钟 | 提示里写明「15 分钟 = 一天最多 32 次」 |
| 多久没动算离开 | 1–240 分钟 | 离开后不检查 |
| 用哪个模型 | 下拉：Sonnet（默认）/ Haiku / Opus / 自定义… | 选「自定义」展开一个输入框填完整模型名；经 `normalize_model` 落盘，怪名字退回默认 |

右键菜单里的开关和间隔改的是同一份配置；后台服务每分钟重读配置，所以设置页保存后最迟一分钟生效。
`modern_settings_dialog.py` 只多 2 行（插节、保存；import 并进既有一行），预算 2401 → 2403。

测试 `tests/test_settings_slack_watch.py`（4 用例）：四行都落在「自动化与联动」且显示已存的值；改了能经 `normalize`
存回去、怪模型名退回默认；配置里是自定义模型名时下拉停在「自定义」且输入框带出来；没 WSL 时开关置灰、保存保持关。
设置域 / 架构守卫族同跑全绿（43 用例）；`ruff check pet tests` 通过。本轮没有重跑全量：改动只有设置页的一节
（控件在新模块里）和两行接线，接口、持久数据格式、生命周期、平台分支都没变，按 AGENTS 的「局部控件行为」口径以
焦点 + 相关族为准。设置页那一节没有在真实设置窗口里打开过（离屏构造覆盖）。

## 四、性能分析

**方法（可复现）**：`.venv\Scripts\python.exe <探针脚本>`，本机 Windows 11 Pro 26300、Python 3.13.15、WSL 里的 Claude Code
（公司座席，`sonnet`），各 1 次（真跑一次就是一次真实的模型调用，不反复刷）。

| 指标 | 实测 | 归属 |
|---|---|---|
| `session_active`（输入桌面名 + 闲置秒数） | 0.04 ms（整个探针含 import 41.7 ms） | 新增稳态：每分钟 1 次，GUI 线程 |
| `is_due` + 读状态文件 | 一次小 JSON 读取，微秒级 | 新增稳态：每分钟 1 次 |
| 真实检查（回看 1 小时） | 20.9 s，9 轮，0 条 | 新增：每 15 分钟 1 次，工作线程 |
| 真实检查（回看 24 小时） | 24.0 s，6 轮，2 条（1 急 1 普通，都带链接） | 同上 |
| 结果落盘 | 一个几 KB 的 JSON，原子替换 | 每次检查 1 次 |

**结论**：
1. **稳态开销**：GUI 线程每分钟多一次 0.04 ms 的系统询问和一次小文件读取；没有新的定时重绘。
2. **新增路径**：每 15 分钟一次 20–25 秒的 wsl.exe（工作线程），只在人在电脑前时；按一天 8 小时在用算最多 32 次。**这是真实的模型调用**（公司座席按用量计），间隔可调到 5–240 分钟，不想跑就关掉开关。
3. **新的系统调用 / 线程**：`OpenInputDesktop` / `GetLastInputInfo`（每分钟）、wsl.exe 子进程 + 1 条 daemon 线程（每次检查）。没有桌宠自己的网络请求。
4. **内存**：最近一次结果（≤8 条）+ ≤200 个键；窗口按需建、和简报窗口同一个类。

## 五、实机运行记录

**环境**：本机 Windows 11 Pro（26300）、WSL 默认发行版里登录着工作账号的 Claude Code（带 Slack 连接器）。
下面只打印结构（布尔 / 数量 / 耗时 / 长度），不打印消息内容。

**人在不在的探测**（`probe_active.py`）：
```
input desktop: 'Default' | idle s: 367.8 | active: True | 41.67 ms
```

**真实检查一：回看 1 小时**（`real_watch.py`，`sw.generate(now, now-60min, "sonnet")`）：
```
ok: True | seconds: 20.9 | turns: 9 | items: 0 | urgencies: [] | with link: 0 | summary len: 0 | denied: [] | error len: 0
```
最近一小时确实没有在等我的消息，模型给了空列表和空概要——这正是「安静」那条路。

**真实检查二：回看 24 小时**：
```
ok: True | seconds: 24.0 | turns: 6 | items: 2 | urgencies: ['high', 'normal'] | with link: 2 | summary len: 63 | denied: [] | error len: 0
```
两条都带永久链接、一急一普通；没有工具被拒（放行名单够用）。

**重启桌宠**（真实 `APPDATA`，`run.bat`；重启前把 `slack_watch.enabled` 写成 true）：`pet-overlay-gate.log` 多一行
`2026-10-14 14:44:35 acquired pid=42456`；新进程日志里没有 Traceback。第一次自动检查（人在、从没查过 → 到点就查）落在
一分钟后的例行检查上，日志只记结构：
```
2026-10-14 14:45:50,443 INFO Slack 关注完成：用时 14 秒，5 轮，0 条，新 0 条
```
`slack-watch.json`（335 字节）随之出现；最近一小时没有在等我的消息，所以桌宠安静。

**测试**：`tests/test_slack_watch.py` 20 用例全绿；简报 / 配置快照 / 菜单 / 会话详情 / 共享壳 / 架构守卫 210 用例全绿；
`ruff check pet tests` 通过。

**全量**（隔离 worktree `bffv3` = 基线 `82f9f7d` + 本补丁，`python -m pytest -q -p no:cacheprovider`，
`QT_QPA_PLATFORM=offscreen`、`APPDATA` 指到临时目录）：
```
4 failed, 5257 passed, 11 skipped, 249 warnings in 447.00s (0:07:27)
```
4 个失败全是这台机器上固定的环境性失败（`image_directory_picker` 路径超 260、`festival_id_guard` 子进程按 cp1252
打印中文、`real_second_process`、`capture_window_rect` 多显示器负原点），不含本改动的代码上同样失败。

**没有验证的部分**：
- 锁屏状态下 `OpenInputDesktop` 的返回：没有真的锁屏去试（锁屏会把这个会话也锁掉）；按 Windows 文档和社区实测，锁屏时输入桌面是 `Winlogon`、普通进程打不开，代码两种情况都按「不在」算。
- 右键菜单里的几项没有在真实桌面上点过（菜单构造与 facade 方法有既有族的用例覆盖同款写法）。
- 提醒气泡的真实外观：实机上第一次自动检查跑在最近一小时、多半没有新条目（安静）；带按钮的气泡在离屏用例里验证。
