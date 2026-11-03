# PR 报告：弹窗里的旧通知点了没反应——卡片带着通知本体跳，名单忘了的也能跳

> **基线**：`3731454c`（main，含 #16）　**分支**：`fix/toast-click-forgotten`　**日期**：2026-11-03
> **范围**：4 个文件（实现 2、测试 2）+ 本报告
> **关联**：[`PR-REPORT-NOTIFICATION-TOASTS-2026-10-28.md`](PR-REPORT-NOTIFICATION-TOASTS-2026-10-28.md)（自家弹窗、点击 → 跳转的链路）、
> [`PR-REPORT-NOTIFICATION-CENTER-2026-10-14.md`](PR-REPORT-NOTIFICATION-CENTER-2026-10-14.md)（通知服务的名单与 `keep`）

## 一、现象与排查

用户 2026-11-03：一些 Slack 和 Chrome 的通知点了没反应，「例如最下方的几个」。

排查（实机，桌宠 pid 49492 的日志 + 后台重放）找出**两个互不相关的原因**，本 PR 只修第一个：

1. **弹窗卡片还在、服务的名单已经忘了那条**（点了没任何反应，连日志都没有）。
   `NotificationService` 的名单只留最近 `notifications.keep` 条（用户是默认的 50，`apps` 是 `*`，所有应用都算进去）；
   自家弹窗 `toast.seconds` 设成 0 时卡片一直留着（最多 50 张），上午 Slack 一小时来 20 多条，叠到后面，
   最底下那几张卡片对应的通知早被挤出名单。点击链路 `AppShell._on_notification_toast_activated` 拿卡片上的 **uid**
   去 `service.activate(uid)`，服务查不到就返回 False，返回值被直接丢掉：不跳、不提示、不记日志。
   这正好对上「最下方的几个」，也解释了日志里有的点击完全没有痕迹。
2. **Chrome 自己已经不认识那条通知**（桌宠报 `launched`，Chrome 什么都不做）。Chrome 收到 `--notification-launch-id`
   后要先在它自己的通知库（`Platform Notifications` leveldb）里查到记录；网页一旦撤掉通知（Gmail 读过邮件会撤、
   claude.ai 回复完也会撤），记录就删了，再派点击就是空操作。解析该库的 WAL：通知中心里现有的 7 条 Chrome 通知
   （全是 claude.ai 网页的，没有一条邮件）里最老的两条（46 h）是「写入后已删除」，重放跳转 Chrome 毫无动静；
   其余 5 条记录还在，重放一条 Chrome 立刻到前台。**没有干净的办法从外面知道 Chrome 还认不认那条**，留作后续
   （见第六节）。
3. **Slack 深链接本身没问题**：重放一条在通知中心里的 Slack 通知，Slack 到前台并切到了那个频道。

## 二、修改文件说明

| 文件 | +/− | 改了什么 | 为什么 |
|---|---|---|---|
| `pet/notification_service.py` | 9 / 3 | `activate(target)`：`target` 可以是 uid **或 `Notice` 本体**；本体直接用、不查名单；只给 uid 而名单里没有的记一行 INFO（`通知跳转：名单里已经没有这条（uid=…），不跳`）再返回 False | 卡片比名单活得久是设计使然（`keep` 与 `toast.seconds=0` 都是用户可设的），跳转不该依赖名单；静默丢弃改成留痕 |
| `pet/app.py` | 4 / 1 | 弹窗点击 `_on_notification_toast_activated` 把 `notice` 本体交给服务（原来只给 `notice.uid`）；岛上「通知」折叠框点行而服务返回 False 时，状态行显示「通知中心里已经没有它了」并重推一遍行数据 | 弹窗这条路从此与名单无关；岛那条路名单里没有只会是刚被挤掉 / 移除的竞态，给个提示而不是装没事 |
| `tests/test_notification_service.py` | 17 / 0 | 新测试：`keep=5` 时读 10 条，名单只剩 5 条；把被挤出去的那条的本体交给 `activate` 照样跳、结果照常走 `activation_done`；只给它的 uid 则返回 False 且日志里有 `uid=3` | 修前红：`AttributeError`（本体被当成 uid 去查名单）；修后绿 |
| `tests/test_app_notification_toasts.py` | 4 / 3 | 既有的点击测试改成断言服务收到的是 `Notice` 本体（uid 7）而不是整数 7；替身服务的 `activate` 改收 `target` | 修前红：`[7] != [Notice(uid=7, …)]`；修后绿 |

### 未改动

`notification_center.activate`（跳转本身）、`ToastCard` / `ToastStack`、名单的 `keep` 规则、配置键、文案表（复用既有 `notices.status.gone`）。

## 三、实现要点

- 服务的 `activate` 用 `isinstance(target, nc.Notice)` 分流，别的调用方（岛上的行、右键菜单「打开」）仍传 uid，接口向后兼容。
- 带本体来的那条如果恰好还在名单里，行为与传 uid 完全相同（同一个对象、同样从未读里去掉、同样发 `unread_changed`）。
- 没改 `keep` 的语义：名单仍只留最近 N 条，岛上的折叠框仍以名单为准。弹窗里能点的范围 = 卡片还在场的范围。

## 四、性能分析

本机（Windows 11，.venv Python 3.13，`timeit` 2 万次均值，名单 50 条）：

| 路径 | 修前 | 修后 | 说明 |
|---|---|---|---|
| `activate(uid)`，uid 在名单最前 | ≈3.0 µs | 3.0 µs | 多一次 `isinstance`（纳秒级，淹没在噪声里） |
| `activate(uid)`，uid 在名单第 50 位 | ≈4.2 µs | 4.2 µs | 线性查名单，不变 |
| `activate(Notice)`（弹窗点击，新路径） | — | **2.7 µs** | 不查名单，比传 uid 还少一次遍历 |
| 名单里没有的 uid，日志关 | ≈1.2 µs | 1.2 µs | — |
| 名单里没有的 uid，INFO 日志开 | ≈1.2 µs | **495 µs** | 一行日志（格式化 + 写文件）；只在用户点到一条名单里已没有的通知时发生，一天几次 |

- 稳态开销：零——所有改动都在用户点击时才执行，没有新线程、定时器、系统调用、磁盘 / 网络访问。
- 新增路径成本与触发频率：弹窗点击省一次名单遍历；名单未命中多一行日志（≈0.5 ms），一天几次。
- 内存：无变化（没有新缓存；卡片本来就持有 `Notice`）。

## 五、实机运行记录

1. **测试**：2 条先红（见第二节的「修前红」）后绿；通知族 6 个文件 **116 passed**（`test_notification_service` /
   `test_app_notification_toasts` / `test_notification_toast` / `test_notification_center` / `test_island_notifications` /
   `test_settings_notifications`）；`ruff check pet/ tests/` 过。`QT_QPA_PLATFORM=offscreen`，`APPDATA` 指向临时目录。
2. **排查用的重放**（本机，后台脚本照桌宠的做法原样发跳转，监视目标应用的顶层窗口）：
   - Chrome、Chrome 已删记录的那条：`chrome.exe` 0.08 s 退出返回 0，3 s 内 Chrome 窗口标题、前台进程都没变。
   - Chrome、记录还在的那条：0.07 s 退出，前台进程变成 `chrome.exe`。
   - Slack（通知中心里的一条）：`os.startfile` 0.12 s 返回，前台进程变成 `slack.exe`，窗口标题变了（切到了那个频道）。
   另外：通知中心里的 Slack 通知消失得很快（43 min 内 20 条），一条 39 min 的通知在两次探测之间就没了——Slack 读过就撤。
3. **实机重启**：桌宠从本分支的工作区重启（pid 54360，10:05），启动日志 **0 ERROR / 0 WARNING**。
   第一次从 scratchpad 路径起时帧序列缓存目录报 `WinError 206`（路径超长，107 条 WARNING），与本改动无关，
   把工作区搬到 `.claude/worktrees/notifyfix` 后重起即正常。
   「名单忘了的卡片点了能跳」要等名单再被挤过 50 条才能在屏上复现——测试覆盖了这条路；修后日志里若再出现
   `通知跳转：名单里已经没有这条` 就说明岛上那条路也碰到了。请用户在今天弹窗攒多之后点最底下几张回报。

## 六、已知限制与后续

- **Chrome 已撤掉的通知**（第一节原因 2）：本 PR 不处理。可选的后续：对已不在通知中心的 Chrome 通知直接打开来源网站
  （`chrome.exe <origin>`），至少不是什么都不发生；或读 Chrome 的 leveldb 判断记录是否已删（依赖 Chrome 内部格式，不建议进产品）。
- 岛上的折叠框仍只显示名单里的 `keep` 条，没变。

## 七、风险与回滚

- 只改一个方法的入参类型（向后兼容）和两处调用；回滚 = revert 这一个提交。
