# PR 报告：自家 Metro 通知弹窗（多条同时叠出、按来源叠放、直接跳转、尊重勿扰）

> **基线**：`edb91a6d`（Merge PR #6）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-26 ~ 2026-10-28
> **范围**：22 个文件（实现 11、测试 10、工具 1）+ 本报告与索引
> **关联**：`pet/notification_center.py`（2026-10-14 起读通知中心、灵动岛通知卡片）；
> 调研笔记在用户本机的 `TODO/windows-notifications.md`（未入库）

## 一、核心特性

Windows 的通知横幅**一次只显示一条**，后面的排队；横幅停留时间又是系统全局设置（本机曾被设成
300 秒，于是后面的通知要等 5 分钟才出来）。这个 PR 让桌宠自己弹通知：用官方的
`UserNotificationListener` 读通知中心（已有），新到的通知用自家的 Metro 卡片在选定的角 / 屏上
**几条同时叠出**；同一来源叠成一摞，点一下直接跳到原消息，不必打开通知中心。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 自家弹窗 | `ToastStack` + `ToastCard`：方角平铺卡片、应用图标磁贴；从屏幕边翻入、悬停倾斜并暂停倒计时、往屏幕边划走关闭；四个角 × 主屏 / 光标所在屏 / 指定屏；停留 0–3600 秒（0 = 一直留着）、最多同时 N 条，多出来的排队补位 |
| 2 | 按来源叠放 | Slack 按工作区 + 频道（或整个 Slack 一摞、或不叠）；Chrome 按发通知的网站（或整个 Chrome、或不叠）。一摞显示最近 3 条，点开原地展开，点哪行跳哪条、只拿掉那一条 |
| 3 | 直接跳转 | 通知数据库 `wpndatabase.db` 里有启动参数（监听接口不给），新通知到的那一轮复制三个库文件到临时目录查一次。Slack 是 `slack://channel?…&message=…` 协议链接，直接打开；Chrome 的 `foreground` 激活照它的 COM 组件那样交给 `chrome.exe --notification-launch-id=…`（Gmail 会打开那封邮件）；其余应用照旧走通知中心 UI 自动化 |
| 4 | 什么时候不弹 | 开读后的第一轮算积压，只进岛不弹；超过 120 秒的旧通知不弹；全屏游戏 / 演示时不弹；**开着 Windows「勿扰」时不弹**（本 PR 收尾时补上）。不弹的照样进灵动岛的通知列表 |
| 5 | 设置 | 新一级域「通知」（桌面组件之后，铃铛图标）三节：读取 / 叠放 / 弹窗。原「自动化与联动 → 通知中心」一节移过来 |

**红线 / 不变量**：

- 弹窗默认**关**；不开时行为与基线完全一致（`_sync_notification_toasts` 不建 `ToastStack`）。
- 读失败、勿扰状态读不到、`chrome.exe` 找不到、启动参数不认识：一律退回原有路径（照常弹 / 走 UIA），不吞通知、不报错。
- 通知数据库只复制后读，从不写 `%LOCALAPPDATA%\Microsoft\Windows\Notifications` 下的活文件。
- 协议链接经 `launchable_uri` 过滤（`file` / `javascript` / `vbscript` / `data` 不开）；Chrome 参数以参数列表传给 `chrome.exe`，不经 shell。

## 二、修改文件说明

`git diff --numstat edb91a6d HEAD`（8 个提交：`b0271bf7` `fea62de4` `b30eeb34` `7b8e830f` `fbb20e45` `bc1ce2ce` `964ae437` `e6b596fe`）。

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/notification_toast.py`（新） | +772 / −0 | `ToastCard`（一条或一摞的卡片：渲染缓存成 pixmap、进退场 / 挪位动画、悬停暂停倒计时、划走、展开 / 收起、行命中）与 `ToastStack`（按 `source_key` 并组、`stack_positions` 摆位、`max_visible` 之外排队、`_MAX_PENDING`=50 封顶、换角换屏）；纯函数 `normalize` / `stack_positions` / `resolve_screen` / `wrap_lines`。收尾提交 `964ae437`：排队满了丢掉最旧的那批时，把它们藏着的卡片窗口 `deleteLater`（之前只从列表里删，隐藏的顶层窗口一直留着） |
| `pet/notification_center.py` | +256 / −14 | `Notice` 加 `launch` / `activation`、`launchable` / `kind` / `source`；`source_key`（Slack 频道 / Chrome 网站 / 不归组）；`launch_targets`（复制库文件查启动参数）与 `with_launch`；`activate` 先走直接打开（协议链接或 Chrome 参数），失败才走 UIA；`chrome_exe`（App Paths 或常见安装位置）；配置 `normalize` 增加 `toast` / `stack` 两块（缺键填默认）；`matches_app` 认 `*` |
| `pet/notification_service.py` | +12 / −2 | 新信号 `arrived(list[Notice])`：这一轮新出现的（旧到新）；开读后第一轮算积压不发 |
| `pet/app.py` | +54 / −2 | `_sync_notification_toasts`（设置开着才建 `ToastStack`，把角 / 屏 / 秒数 / 条数 / 叠放 / 明暗传进去）、`_on_notifications_arrived`（全屏 / 勿扰 / 太旧不弹，每次记一行 INFO）、`_on_notification_toast_activated`（走同一条 `service.activate`）；岛卡片的「能跳」改为 `in_center or launchable`；新的跳转结果 `launched` 的状态文案 |
| `pet/platform_win.py` | +27 / −0 | `quiet_hours_profile()`：用 `NtQueryWnfStateData` 读 `WNF_SHEL_QUIETHOURS_ACTIVE_PROFILE_CHANGED`（0 关 / 1 仅优先 / 2 仅闹钟）。勿扰没有公开 API，这是 Windows 通知面板自己读的状态；读失败当 0 |
| `pet/settings_notifications.py` | +126 / −2 | 「通知」页三节（`notification_sections`）；叠放下拉、弹窗开关 / 角 / 屏（当前没接上的屏单列一项保留）/ 秒数（0 显示「一直留着」）/ 条数；开关关着时其余四项置灰；保存写回 `toast` / `stack` |
| `pet/modern_settings_dialog.py` | +6 / −1 | 注册新一级域「通知」，移除「自动化与联动」里的通知中心一节 |
| `pet/settings_widgets.py` | +2 / −0 | 侧栏图标表登记 `bell` |
| `pet/context_menus/icons.py` | +11 / −0 | 自画铃铛图标 |
| `pet/locale/zh.json` / `en.json` | +37 / −2 各 | 新文案（弹窗、叠放、屏幕选择、跳转结果）；弹窗说明写明全屏 / 勿扰时不弹、建议关掉系统横幅 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_notification_toast.py`（新） | +324 / −0 | 配置归一、摆位纯函数（四个角、放不下截断）、选屏；Qt：叠出顺序与位置、排队补位、到点消失与悬停暂停、点击 / 关闭框 / 划走、换角、同 uid 不重弹、Slack 频道并组与回到角上、一摞三行 +「还有 N 条」、其他应用不归组、点一摞展开 / 点行跳那条 / 点标题收起、叠放选择、Chrome 按网站、新消息重新倒计时、0 秒一直留着；**排队溢出时丢掉的卡片窗口被删除**（`964ae437` 的回归，修前红） |
| `tests/test_app_notification_toasts.py`（新） | +113 / −0 | 壳层胶水：设置关着不建、太旧的不弹且图标跟进、全屏不弹、**勿扰（1 / 2）不弹**（`bc1ce2ce` 的回归，修前红）、点击走 service、关掉清空、叠放配置传到弹窗 |
| `tests/test_platform_win_busy_state.py` | +32 / −0 | `quiet_hours_profile` 解码（0 / 1 / 2 / 空 / NTSTATUS 失败 → 0），以及真实调用返回 0–2 |
| `tests/test_notification_center.py` | +197 / −2 | `parse_launch` / `launchable_uri` / `launch_targets`（真 SQLite 夹具）/ `with_launch` / `source_key` / `activate` 的直接打开与退路 / Chrome 参数与 `chrome_exe` |
| `tests/test_notification_service.py` | +33 / −0 | `arrived`：第一轮积压不发、之后只发新的、旧到新 |
| `tests/test_settings_notifications.py`（新） | +134 / −0 | 「通知」页三节、默认值、保存 round trip、开关联动置灰、没接上的屏保留、0 秒文案 |
| `tests/test_desktop_pet_features.py` / `test_menu_layout.py` / `test_settings_english.py` / `test_settings_interaction_tabs.py` | +13 / −11 | 钉着「AI 与对话」页序号的断言改成按名字找（新域插在前面）；英文文案键 |

### 工具

| 文件 | 增删 | 用途 |
|---|---|---|
| `tools/notification_toast_demo.py`（新） | +203 / −0 | 不开桌宠单独看弹窗：`--sample N`、`--replay N`（通知中心里已有的）、`--live`（盯新来的）、`--list-screens`、`--corner` / `--screen` |

### 未改动

- `pet/island*`：岛里的通知列表、未读数照旧，只改了「能跳」的判断条件（在 `app.py` 里）。
- 没有改 Windows 的任何设置：「显示通知横幅」要用户自己按应用关（文案里说明了），否则会弹两遍。

## 三、实现要点

- **线程**：读通知中心、复制数据库查启动参数、UIA 激活都在 `NotificationService` 的 daemon 线程里；结果经排队信号回 GUI 线程合并；`ToastStack` / `ToastCard` 只在 GUI 线程。`quiet_hours_profile` 是一次 ntdll 调用，在 GUI 线程的 `arrived` 处理里直接读。
- **为什么复制数据库**：监听接口不给启动参数；`wpndatabase.db` 被 `WpnUserService` 一直开着写，只能复制三个文件（含 `-wal` / `-shm`）到临时目录读，读完删。只在「这一轮有新通知」时做，`Notification.Id` 就是监听接口的 id（实测 22/22 对上）。
- **勿扰为什么用 WNF**：`SHQueryUserNotificationState` 不反映勿扰（实测勿扰开着它仍是 2 = BUSY）；注册表 `CloudStore` 里是二进制 blob。WNF 状态是 Windows 通知面板自己读的，ntdll 导出、无需权限。未公开接口，所以读失败一律当「没开」——最坏是勿扰时照常弹，不会吞通知。只要开着勿扰（1 或 2）就不弹，没有区分「优先通知」名单（见七）。
- **卡片生命周期**：卡片是无父的顶层 `Tool` 窗口；正常退场 `finished → deleteLater`；被挤下去的 `park()` 藏起来、保留剩余时间；排队上限 50，溢出的那批随之 `deleteLater`（收尾修复）。

## 四、性能分析

**方法（可复现）**：脚本在本会话 scratchpad（`perf.py` / `readcpu.py` / `overflow.py` / `leak.py`），
以仓库根为工作目录，用 `.venv\Scripts\python.exe` 运行；`QT_QPA_PLATFORM=offscreen`。
环境：Windows 11 Pro 26300、Intel 20 线程、Python 3.13.15、PySide6 6.12.0；通知中心当时 33–36 条。

| 指标 | 实测 | 归属 |
|---|---|---|
| 一轮读通知中心 `read_toasts`（每 `poll_seconds`=3 s 一次，daemon 线程） | `["slack"]` 20 条：挂钟中位 461 ms、CPU 中位 94 ms；`["*"]` 36 条：挂钟 565 ms、CPU 109 ms（max 156 ms）；n=10 | 既有路径（10-14 起）；`*` 比只读 Slack 多约 15 ms CPU / 轮 |
| 新通知到时查启动参数 `launch_targets`（复制 3 个库文件 + SQLite 查询） | 5 个 uid：中位 21.3 ms、最大 25.3 ms；n=10 | 新增，**只在有新通知的那一轮**，daemon 线程 |
| `quiet_hours_profile()` | 中位 1.6 µs、p95 1.9 µs、最大 142 µs；n=10000 | 新增，每批新通知一次 |
| `_fs_user_busy_state()`（对照） | 中位 59.6 µs、p95 188 µs；n=10000 | 既有 |
| 弹一张卡片（`push` + `processEvents`） | 首张 3.7 ms（含首次渲染缓存），之后 0.6–0.8 ms | 新增，每条新通知一次，GUI 线程 |
| 内存：4 张卡片在场 | RSS +2.66 MB | 新增 |
| 内存：15 轮 × 20 条弹出再清空（动画开 / 关、同源 / 全不同源） | 第 8 轮起 RSS 不再增长（63.9 / 65.7 / 64.5 MB），活着的 `ToastCard` = 0 | 新增，无累积 |
| 内存：一直留着、80 条全不同源、不清空 | 修前：留 50 条、活着 80 张卡片（30 张隐藏窗口泄漏）；修后：活着 50 张，封顶 | `964ae437` 修复 |

**结论**：

1. **稳态开销**：没有新通知时，新代码不运行任何定时器（卡片的倒计时、动画只在卡片在场时存在）。稳态成本仍是既有的轮询：约 100 ms CPU / 3 s ≈ 单核 3%，`apps` 设成 `*` 比只读 Slack 多约 15%（多读的那些通知）。
2. **新增路径**：每批新通知：一次 ~21 ms 的库文件复制查询（daemon 线程）+ 每张卡片 ~1 ms 的 GUI 工作 + 2 µs 的勿扰查询。触发频率 = 新通知频率（本机以 Slack 为主，一天几十到上百条）。
3. **新的系统调用 / 磁盘 / 线程**：磁盘——每批新通知复制约 1 MB 的通知库到 `%TEMP%` 再删；系统调用——`NtQueryWnfStateData`、跳转时 `ShellExecute`（协议链接）或 `CreateProcess`（`chrome.exe`）；不新增线程、不联网。
4. **内存**：在场卡片约 0.6 MB / 张；排队上限 50，在场 + 排队最多 50 个卡片窗口；反复弹出、收起没有累积。

## 五、实机运行记录

本机：三块屏（主屏 AW3821DW + 两块竖屏），桌宠从源码运行（`run.bat`）。

**前提复现（2026-10-26）**：`HKCU:\Control Panel\Accessibility\MessageDuration` = `300`，系统横幅一次一条、每条停 5 分钟，后面的排队——这是做这个功能的起因（已在系统设置里改回 5 秒）。

**弹窗与跳转（2026-10-26，前几个提交）**：
- 三块屏四个角都弹过；PowerShell 发的真通知 0.6 秒后由弹窗弹出（当时 2 秒轮询）。
- 据当时的提交说明（`fea62de4` / `fbb20e45`）：Slack 通知点卡片直接跳到那条消息，不打开通知中心；
  Chrome 的启动参数格式在 Chrome 155 上实测（比旧版多一段），点了交给 `chrome.exe`。收尾这轮没有重新点测这两条跳转。

**收尾验证（2026-10-27 23:55 ~ 2026-10-28 00:03，合入全部 8 个提交后重启桌宠 pid 6884）**：

```text
# 桌宠日志 %APPDATA%\big-fat-fish\pet-6884.log；通知由 PowerShell 的 WinRT ToastNotifier 发出
sent 23:56:02.395 Toast test 1
sent 23:56:02.712 Toast test 2
2026-10-27 23:56:04,295 INFO 通知弹窗：弹出 2 条（太旧不弹 0 条）
```

- **用户确认**：主屏右上角出现两张叠着的 Metro 卡片（「Toast test 1 / 2」）。发出到弹出约 1.6–1.9 s（3 秒轮询）。
- 之后两次弹出是用户自己应用的真实通知，日志里只有条数（内容从略）。

**勿扰（失败 / 抑制路径）**：

```text
# 探针：每 0.5 s 读一次 WNF 状态，用户在通知面板里开勿扰、3 秒后关掉
23:43:09 (0, 550, '00000000')
23:50:34 (0, 551, '01000000')    ← 开勿扰
23:50:40 (0, 552, '00000000')    ← 关勿扰

# 用户再次打开勿扰后
quiet_hours_profile = 1
sent 00:02:32.985 Toast test 3
2026-10-28 00:02:34,260 INFO 通知弹窗：do_not_disturb，1 条不弹
```

同一时刻 `SHQueryUserNotificationState` 一直报 2（BUSY）——它不反映勿扰，所以必须读 WNF。

**无法自动验证的部分**：勿扰状态由用户在系统 UI 里切换，测试里只能假冒 `NtQueryWnfStateData` 的返回；实机探针（上面）证明了真实值 0 → 1 → 0 的对应关系。「优先通知」名单的应用在勿扰时是否该弹，没有验证（见七）。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check .` | 通过 |
| `git diff --check edb91a6d HEAD` | | 通过 |
| 聚焦 | `pytest -q tests/test_notification_toast.py tests/test_app_notification_toasts.py tests/test_platform_win_busy_state.py tests/test_notification_center.py tests/test_notification_service.py tests/test_settings_notifications.py` | 全过 |
| 断言有效性 | 勿扰与排队溢出两条回归测试在改产品代码之前跑过，均为红（`AttributeError: quiet_hours_profile` / `assert not True`），改后转绿 | 已确认 |
| 全量 | `python -X faulthandler -m pytest -q -p no:cacheprovider`（PowerShell 启动，`QT_QPA_PLATFORM=offscreen`，`APPDATA` 指向临时目录；在 `e6b596fe` 上） | 5774 passed / 14 skipped / 5 failed，731 s。其中 4 个是本机环境基线（`test_image_directory_picker_…` 路径超 260、`test_festival_id_guard_survives_optimize` 与 `test_real_second_process_refused_on_overlay_topology` 子进程按 cp1252 解码、`test_capture_window_rect_coordinates_and_clamping` 多屏负原点），与改动无关；第 5 个 `test_architecture.py::test_window_private_surface_frozen` 是本轮引入的：`app.py` 里写成 `platform_win._fs_user_busy_state()` 命中了「`win._x` 私有面」正则。改回按名字导入（下一个提交），`tests/test_architecture.py` + 通知相关 5 个文件复跑 224 passed。这处改动只是导入写法，没有再跑一遍全量 |
| 架构红线 | `pytest -q tests/test_architecture.py` | 修正后通过 |

## 七、已知限制与后续

- **轮询**：没有包身份（MSIX / sparse package），`NotificationChanged` 事件不可用，只能每 3 秒读一次；延迟最长约一个轮询周期 + 0.5 s，稳态约单核 3%。做包身份之后可以改成事件驱动。
- **勿扰的「优先通知」名单**：开着勿扰就一律不弹，没有读 Windows 的优先应用名单（同样是未公开的存储）。
- **系统横幅要手动关**：不改 Windows 设置；用户需要在「设置 → 系统 → 通知」里按应用关掉「显示通知横幅」，否则同一条弹两遍。
- **WNF 状态名是未公开接口**：Windows 更新后若改名或改格式，`quiet_hours_profile` 读失败返回 0，退化为「勿扰时照常弹」。
- 其他应用（非 Slack / Chrome）暂不归组；没有协议型启动参数的应用跳转仍走通知中心 UI 自动化。

## 八、风险与回滚

- **开关**：设置「通知 → 弹窗 → 自己弹通知」，默认关。关掉后清空在场卡片、不再建。
- **配置**：`notifications` 下新增 `toast`（`enabled` / `corner` / `screen` / `seconds` / `max_visible`）与 `stack`（`slack` / `chrome`）两块；旧配置没有这些键时由 `notification_center.normalize` 填默认值，无需迁移；回退到旧版本时这两块被忽略。
- **设置页**：新一级域「通知」（三个稳定分组，满足 `SETTINGS-CHANGE-GATES.md` 对一级域的要求）；原「自动化与联动 → 通知中心」一节移除，键不变。
- **回滚**：`git revert` 这 8 个提交即可；运行时只在 `%TEMP%` 下留过临时库副本（每次读完即删），无其他落盘状态。
