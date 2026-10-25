# PR 报告：灵动岛上的通知中心——Windows 通知中心里的 Slack 通知铺成卡片，点一条跳回那条消息（2026-10-14）

> **基线**：`0fab2ab`（docs: 报告里的用户目录路径换成占位符，`feature/claude-session-fish`）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-14
> **范围**：17 个文件（实现 9：新增 4、改 5；测试 6：新增 3、改 3；依赖 1；文档 1）
> **关联**：[`PR-REPORT-WORK-BRIEFING-2026-10-12.md`](PR-REPORT-WORK-BRIEFING-2026-10-12.md)（胶囊上那排按钮的第一个）、
> [`PR-REPORT-ISLAND-HISTORY-TILES-2026-10-14.md`](PR-REPORT-ISLAND-HISTORY-TILES-2026-10-14.md)（卡片风格）、
> [`PR-REPORT-UI-LANGUAGE-ISLAND-2026-10-14.md`](PR-REPORT-UI-LANGUAGE-ISLAND-2026-10-14.md)（文案键）

## 一、核心特性

**问题**：Windows 一次只弹一条 toast、叠不起来（macOS 那种一摞是没有的），Slack 连着来几条就只看到最后一条；
通知中心里虽然都在，但得先点开、再在一长列里找。

**做了什么**：灵动岛胶囊上、简报图标右边，多一个铃铛；有新通知时铃铛变琥珀色带角标。点铃铛展开卡片，
里面新增一个「通知」折叠框（Windows Phone 式平铺卡片，和「最近的对话」同一套）：每条一块卡片——左边是发通知
的应用自己的图标（Slack 的 logo，从系统读出来的 PNG），右边是频道 / 对方的名字 + 多久以前，下面两行「发送人:
消息」。**点一条，Slack 跳到那条消息**。右键：跳 / 移除 / 清空。设置页「自动化与联动」新一节「通知中心」：
开关、读取间隔、认哪些应用（默认只认 Slack；将来别的应用照此加）。

**为什么能跳到具体消息**（这是本功能的关键，先后试了四条路）：

| 路 | 结果（2026-10-14 实测） |
|---|---|
| `UserNotificationListener` 读出来的内容里找频道 id / 启动参数 | 没有。只有应用名、两段文字、创建 / 过期时间、一个整数 id。 |
| `slack://channel?team=<T>&id=<频道名>` | 只认频道 id；给名字**不跳，还把 Slack 弄成「Something went wrong」报错页**。 |
| Slack 本地缓存里找「频道名 → id」 | `IndexedDB` 是压缩的（扫 4004 个文件 / 931 MB，0 处明文命中）；`root-state.json` 只有 workspace 的 id / 名 / 域名。 |
| **打开通知中心，用 UI 自动化找到那条并 Invoke** | **成功**。Windows 把激活交给 Slack，Slack 带着它自己的启动参数跳到那条消息（窗口标题切成那个频道、消息在视图底部），那条 toast 随之从通知中心消失。 |

所以「跳转」= `ms-actioncenter:` 打开通知中心 → UIA 在 `MainListView` 的 `ListViewItem` 里按「标题 + 正文前 30 字」
认出那条 → `InvokePattern.Invoke()`。通知中心里已经没有它了（用户在 Windows 那边划掉了、或者跳过一次了）就退一步
`slack://open?team=<id>` 打开 Slack（team id 读 Slack 自己的 `root-state.json`），卡片上那条名字变灰提示只能这样。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 读通知 | WinRT `UserNotificationListener`，隔 3 秒（可设 2–60）在工作线程里读一次；没有包身份的进程订阅不了变更事件（实测 `Element not found`），只能轮询。上一轮读过的条目按 id 复用，不再逐条取应用信息。 |
| 2 | 合并 | 纯函数 `merge`：这次读到的是「通知中心里现有的」；不在了的保留、标 `in_center=False`；用户移除过的（`hidden`）不再出现；新到旧、最多 `keep` 条。 |
| 3 | 铃铛 | `set_notification_count(None/0/n)`：不画 / 安静 / 琥珀色 + 角标；排在简报图标右边（简报不显示时顶上它的位置）；可点区与简报的正好不重叠。 |
| 4 | 卡片 | `NotificationPanel`：表头 + 行卡片，未读行左缘主题色竖条，正文两行按字折（CJK 没空格也行）、末尾省略；多了在框里滚动（6 行）。点铃铛 = 展开卡片 + 打开这个框 + 全部标为已看。 |
| 5 | 跳转 | 见上；在工作线程里跑（COM 自己初始化），结果经信号回 GUI，表头显示「已交给 Slack 打开 / 通知中心里已经没有它了…」。 |
| 6 | 设置 | `notifications` = `{enabled, poll_seconds, keep, apps}`；设置页一节；非 Windows / 没装包时开关置灰并说明。 |
| 7 | 中英 | 14 个文案键（铃铛提示、表头、菜单、结果），英文单复数成对。 |

**红线 / 不变量**：
- 通知内容只在本进程内存里：不落盘、不进日志、不进任何网络请求（日志只记成败，DEBUG 级）。
- 胶囊上原有各项（头像 / 名字 / 信息槽 / 会话计数 / 连接图标 / 简报）位置与宽度算法不变；铃铛不显示时胶囊宽度逐像素与改前相同（测试守着）。
- 「最近的对话」折叠框的一切行为不变；两个折叠框任一开着，卡片都不自动收起。
- 非 Windows / 缺包：`available()` 为 False，服务不建、铃铛不画、卡片里没有这个框、设置页开关置灰——其余一切照旧。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/notification_center.py`（新） | +363 | 不碰 Qt 的那一层：`normalize` / `matches_app`（配置）；`Notice`（frozen dataclass，`sender` / `message` 由 `split_body` 拆「发送人: 消息」，冒号后没空格、名字超 48 字都不算发送人）；`merge`（见上）；`read_toasts`（WinRT，`asyncio.run`，`known` 复用，`want_logos` 顺手取应用图标 PNG）；`remove_from_center`；`slack_team_id` / `fallback_url`；`_invoke_in_center`（UIA）；`activate`（先通知中心、再退路，返回 `activated` / `opened_app` / `gone` / `failed`）。所有系统调用可注入替换。 |
| `pet/notification_service.py`（新） | +224 | `NotificationService(QObject)`：定时器 + daemon 线程读、`_done` 信号回 GUI 合并；未读集合（`mark_all_seen`）、`activate` / `dismiss` / `clear`、`apply_settings`（关掉时停表清空并通知岛）、轮次号丢弃停表后的晚到结果、读出错不带病。 |
| `pet/island_notification_panel.py`（新） | +340 | 卡片里的「通知」折叠框：`_NoticeRow`（图标槽 26px、标题 + 多久以前、正文两行）、`NotificationPanel`（表头 / 滚动列表 / 状态行 / 右键菜单 / `set_logos` 把 PNG 字节变成按 DPR 缩放的图标）、`body_lines`（按宽度折行）。样式复用 `island_history_panel.tile_colors` / `_font`。 |
| `pet/settings_notifications.py`（新） | +61 | 设置页「通知中心」一节：`ToggleSwitch` + `BrowserSpinBox`（秒）+ `QLineEdit`（应用名片段）；`save_notification_settings` 经 `normalize` 落盘。 |
| `pet/dynamic_island.py` | +147 / −17 | 铃铛：`set_notification_count` / `notification_tooltip` / `_paint_bell_icon`；按钮排版抽成 `_toolbar_left` + `_button_rect`（简报与铃铛共用；可点区右边从 +8 改为 +半个间距，两个按钮正好不重叠）；`_capsule_width` 与内容层缓存 key 加入铃铛；`event` 的悬停提示、`mouseReleaseEvent` 的命中；卡片里插入 `NotificationPanel`（在「最近的对话」上面）：`set_notifications` / `show_notification_status` / `_on_bell_clicked`；`_sync_collapse_timer` 改为看两个框。四个新信号。 |
| `pet/app.py` | +105 / −0 | `_sync_notification_center`（岛在才建服务，配置重载时 `apply_settings`）、`_push_island_notifications`（Notice → 行字典）、`_push_island_notification_count`、铃铛 / 行点击 / 右键 / 折叠四个槽、`_on_notification_activation_done`（结果文案）。挂在 `_sync_dynamic_island` 末尾，和简报按钮同一条路。 |
| `pet/config.py` | +6 / −0 | 顶层键 `notifications`：默认值、`reload()` 白名单、`_normalize_pet_settings` 归一化、`set()` 触发归一化的键集合。 |
| `pet/modern_settings_dialog.py` | +3 / −1 | import 并进 `settings_vscode` 那一行、插进「自动化与联动」第 3 节、保存 1 行。实测 2401 行，预算同步上调。 |
| `pet/locale/zh.json` / `en.json` | +12 / +13 | 14 个键（英文 `island.notifications.unread` 成对单复数）。 |
| `requirements.txt` | +8 | `winrt-Windows.UI.Notifications`、`.Management`、`winrt-Windows.ApplicationModel`、`.Core`（都是 `>=3.0; platform_system == "Windows"`），带用途注释。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_notification_center.py`（新） | +120 | 配置归一化（夹值、空应用名退默认）；`matches_app`；`split_body` 的四种边界；`merge`（新到旧、消失的标灰、hidden、keep、这次读到的必在中心）；`slack_team_id` / `fallback_url`；`activate` 三条路（参数化）+ gone / failed / UIA 抛异常走退路；`_center_probe`。 |
| `tests/test_notification_service.py`（新） | +149 | 假读取 + 同步「线程」：合并与未读计数、图标只补一次、上一轮结果回传复用、看过 / 跳 / 移除 / 清空、关掉停表清空、重开立刻读、停表后的晚到结果丢弃、读出错不带病、不可用平台永不启用。 |
| `tests/test_island_notifications.py`（新） | +216 | 铃铛：不给计数不画、占一格、排在简报右边且可点区不重叠、去掉后宽度逐像素回到原值；提示文案与内容层缓存 key 随计数变；点铃铛 = 展开 + 开框 + 发信号 + 不自动收起；关着时框不出现。面板：三层文字、两行正文、未读竖条、灰名字、占位点、滚动高度；PNG 字节变图标、坏字节退回占位；点行 / 右键 / 折叠 / 状态行；英文表头与菜单；`body_lines` 折 CJK、按空格断、省略。 |
| `tests/test_architecture.py` | +3 / −1 | 设置页行数预算 2399 → 2401，登记原因。 |
| `tests/test_config_schema.py` | +1 / −0 | 白名单快照加 `notifications`。 |
| `tests/test_single_process_shared.py` | +6 / −0 | 假岛补 `set_notification_count` / `set_notifications` 空方法（全量时发现，见第五节）。 |

### 未改动

- `pet/island_history_panel.py`：只被 import（`_font` / `tile_colors`），一行没动。
- `pet/work_briefing_ui.py`：简报按钮的状态机不变；只是岛侧的排版函数换了名字（`_briefing_icon_left` 仍在）。
- 没有给右键菜单加入口：铃铛就是入口。

## 三、实现要点

- **线程与信号**：读（WinRT）和跳（UIA + `os.startfile`）都在 daemon 线程里；服务只在 GUI 线程改状态（`_done` / `_activated` 跨线程排队）。UIA 的 COM 在线程里 `CoInitialize` / `CoUninitialize` 成对。轮次号（`_generation`）让停表 / 重排之后的晚到结果作废，和工作简报服务同一套路。
- **为什么轮询而不是事件**：`UserNotificationListener.NotificationChanged` 对没有包身份的进程直接报 `Element not found`（探针实测）。3 秒一轮，每轮在工作线程里 ~50 ms（见性能）。
- **复用上一轮**：`get_notifications_async` 本身几十毫秒，贵的是逐条 `app_info` / 文字（~10 ms 一条）；同一个 id 的通知内容不会变，所以把上一轮的 `Notice` 传回去按 id 复用，只解析新出现的。
- **在通知中心里认哪条**：UIA 里每条是一个 `ListViewItem`，`Name` 是它所有文字拼起来的（实测 534 字）；用「标题 + 空白归一后的正文前 30 字」双条件匹配，两条同频道同前缀的消息也分得开（正文前 30 字里含发送人）。找不到立刻返回（通知中心开着、列表里没有）而不是等满 2 秒。
- **跳转后的状态**：那条 toast 被 Windows 消费掉，下一轮读不到 → `merge` 标 `in_center=False`，卡片上名字变灰；再点就只能打开 Slack。卡片不自动删掉它（用户可能还想看内容），右键「移除」才删。
- **铃铛的「新」**：出现之后用户没打开过通知框的算新；点铃铛 / 展开框 = 全部标为已看；跳过的那条单独标为已看。
- **取舍**：没做「点通知时不闪一下通知中心」——UIA 必须等它开着才能找到元素，实测闪 0.3 秒左右，Slack 一到前台它就自动关了。也没做 Slack API（要公司 token，不进个人机器的配置）。

## 四、性能分析

**方法（可复现）**：`.venv\Scripts\python.exe <探针脚本>`（脚本只打印耗时与结构；本机 Windows 11 Pro 26300，
Python 3.13.15，PySide6 6.12.0，winrt-* 3.2.1，通知中心里 20 条 Slack 通知，样本 5 次）。

| 指标 | 实测 | 归属 |
|---|---|---|
| `access_status()`（问一次权限） | 25 ms | 新增，启动时 1 次（服务里每轮读也会问，含在下一行里） |
| `read_toasts` 冷读（逐条解析 20 条） | 241 / 217 / 191 / 230 / 226 ms | 新增，只在第一轮和有新通知时才逐条解析新的那几条 |
| `read_toasts` 热读（20 条全部按 id 复用） | 45.0 / 47.9 / 53.0 / 47.7 / 47.3 ms | **新增稳态路径**：每 3 秒一次，工作线程 |
| 取应用图标（Slack logo PNG 3539 B） | +50 ms 左右（含图标那一轮 252–305 ms） | 新增，每个应用一生一次 |
| 服务首轮（建服务 → `changed` 信号） | 2.5 s 内收到 1 次 `changed`（20 条） | 新增，启动后 6 秒才开始 |
| 跳转：打开通知中心 → UIA 找到 → Invoke | 找到 0.26–0.28 s；点卡片到 Slack 标题切换 **1.7 s** | 新增，用户点一次跑一次 |
| 读通知那条线程的 CPU | 50 ms / 3 s ≈ 1.7% 的一个核（工作线程，GUI 线程只做合并与重绘） | 新增稳态 |

**结论**：
1. **稳态开销**：GUI 线程没有新的周期性工作（合并只在列表真变了时发生，且 `merge` 是 20 条的纯 Python，微秒级）；新增一条工作线程，每 3 秒醒一次做 ~50 ms 的 WinRT 调用。岛的 `paintEvent` 内容层缓存 key 多一项整数，命中率不变。
2. **新增路径**：冷读 ~220 ms 只在有新通知时发生，且只解析新的那几条（不是整列）；跳转 1.7 s 是用户点一次跑一次，其中 Slack 自己导航占大头。
3. **新的系统调用 / 线程**：WinRT 通知读取（每 3 秒）、UIA + `ms-actioncenter:` + `slack://`（点击时）、1 条 daemon 线程（和 `now_playing` 同模式）。没有网络、没有磁盘写（Slack 的 `root-state.json` 只在跳转退路时读一次）。
4. **内存**：最多 `keep`（默认 50）条 `Notice`（每条几百字节）+ 每个应用一张 PNG 字节（3.5 KB）+ 面板里最多 50 个行控件（和「最近的对话」同量级）。

## 五、实机运行记录

**环境**：本机 Windows 11 Pro（26300）、Store 版 Slack、通知中心里 20–21 条 Slack 通知、Windows「让应用访问通知」已开。
下面所有输出都只打印结构（长度 / 布尔 / 耗时），不打印通知内容。

**根因 / 前提的现场复现**：

```
access: 1 (ALLOWED=1) | 10 ms
toasts in action center: 20 | 50.4 ms
by app: {'Slack': 20}
app id: 91750D7E.Slack_8she8kybcnzg4!Slack
Notification attrs: ['as_', 'expiration_time', 'visual']          ← 没有启动参数
binding ToastGeneric: True
text elements: 2 | lengths: [13, 235]
binding hints (keys): ['hint-originalTemplate']
```

```
token = L.add_notification_changed(on_changed)
OSError: [WinError -2147023728] Element not found.                 ← 变更事件对本进程不可用，只能轮询
```

深链接按频道名（失败，且弄坏 Slack）：
```
team id shape: T 9 | domain set: True | channel from toast: len 13
navigated by name: NO | windows after: 1 | title mentions channel: False
（随后 Slack 窗口显示 Something went wrong，用户点 Reload 恢复）
```

通知中心 UIA 激活（成功）：
```
center found after 0.26 s
list items: 3 | hit: True
invoke pattern ptr truthy: True
invoked at 0.28 s
hwnd is fg: True | segs: [36, 16, 13, 5] | seg0 suffix: (Channel)   ← Slack 窗口标题切到那条通知的频道
toast still in action center: False
```

**改后，真实服务 + 真实 WinRT（`real_service.py`）**：
```
access_status: allowed | 26 ms
read_toasts cold x5: [241.6, 217.4, 190.9, 229.7, 226.1] ms | items 20
read_toasts warm (known reused) x5: [45.0, 47.9, 53.0, 47.7, 47.3] ms | same items: True
with logo: 252.0 ms | logos {'91750D7E…': 3539}
service: changed→ [20] | unread 20 | newest shape: [(13, 498, True, False), (26, 498, True, False), (13, 67, True, True)] | team id shape: T 9
```

**重启桌宠（真实 `APPDATA`，`run.bat`）**：`pet-overlay-gate.log` 多一行 `2026-10-14 14:08:20 acquired pid=39784`；
`pet-39784.log` 里没有 Traceback，也没有通知相关的报错。

**真实桌面上看到的**（截图只我看了，含公司内容，不入库）：
- 胶囊上、简报图标右边出现琥珀色带角标的铃铛（英文界面，提示「Notifications · 20 new」那一型）。
- 用程序点铃铛（`SetCursorPos` + `mouse_event` 点我们自己的窗口）：卡片展开，最上面是「Notifications (21) · Collapse」，
  下面每条一块卡片，左边 Slack 自己的图标，右边频道名 + 「just now / 3 min ago」，两行正文末尾省略；第一条左缘主题色竖条；
  铃铛变回安静色（已看）。
- 点第一条（`click_row.py`）：
  ```
  before: toast count 21 | slack title has channel: False
  slack switched to that channel: True | 1.7 s
  toast count after: 20 (activated toast leaves the center)
  ```

**测试**：
- 新增 3 个文件 26 用例全绿；相关族（i18n、岛、简报、设置页、配置快照、架构守卫）266 + 68 用例全绿；`ruff check pet tests` 通过；`git diff --check` 通过。
- 全量：在隔离 worktree（`bffv3`，基线 + 本补丁）里跑，结果见本节末尾的「全量结果」。

**没有验证的部分**：
- 右键菜单的「移除 / 清空」没有在真实桌面上点过（离屏用例覆盖；`remove_notification` 的真实调用没跑）。
- 通知中心里**已经没有**那条时的退路（`slack://open?team=`）：只在探针里跑过 `slack://open?team=<id>`（0.4 秒到前台），没有从卡片上走过这条路。
- 设置页那一节没有在真实设置窗口里打开过（离屏构造 + 域认领用例覆盖）。
- 非 Slack 应用：`apps` 加别的名字能读到（`matches_app` 用例），但别的应用的「跳转」只是通用的通知中心激活，没有实测。

**全量结果**（隔离 worktree `bffv3` = 基线 `0fab2ab` + 本补丁，`python -m pytest -q -p no:cacheprovider`，
`QT_QPA_PLATFORM=offscreen`、`APPDATA` 指到临时目录，从 Git Bash 启动）：

```
5 failed, 5232 passed, 11 skipped, 249 warnings in 472.20s (0:07:52)
```

5 个失败里 4 个是这台机器上固定的环境性失败（`image_directory_picker` 路径超 260、`festival_id_guard` 子进程按
cp1252 打印中文、`real_second_process`、`capture_window_rect` 多显示器负原点），不含本改动的代码上同样失败。第 5 个
`test_single_process_shared.py::test_shared_island_toggle_all_windows` 是本改动引入的：那个用例的假岛没有
`set_notifications` / `set_notification_count`（这台机器上 WinRT 可用，服务真的建起来了）——给假岛补了两个空方法
（和它已有的 `set_briefing_state` 同款），单跑该文件 + `test_island_shell_wiring.py` 38 用例全绿。
