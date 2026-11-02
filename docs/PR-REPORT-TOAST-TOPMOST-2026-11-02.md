# PR 报告：通知卡片被最大化窗口盖住后自己回来（重排 + 看门狗重新置顶）

> **分支**：`fix/toast-topmost-reassert`　**日期**：2026-11-02
> **提交**：`02b4e10d`、`<报告>`
> **范围**：实现 1 个文件 + 测试 1 个文件（改）
> **过程**：用户 2026-11-02 14:00 截图「消息提示中间空了一块，查找一下原因」；排查见「实机运行记录」

## 一、核心特性

- 修一个只在长时间运行的桌宠里才出现的缺陷：几张通知卡片**窗口在、位置对、内容也画了**，但屏幕上看不见，
  叠放里就缺一块。原因是卡片是从不激活的置顶工具窗，Qt 只在建窗时写一次 `WS_EX_TOPMOST`，被别的窗口压
  到下面后再也不自己回来（`platform_win._set_windows_topmost` 的注释写的就是这件事——灵动岛当年同一个坑）。
- `ToastStack._reflow` 末尾 + 在场期间每 2 s 一次的看门狗：把在场的卡按**老 → 新**重新 `SetWindowPos(HWND_TOPMOST)`
  （最新的最后插、在最上）；有真全屏应用（`QUNS_RUNNING_D3D_FULL_SCREEN` / `PRESENTATION_MODE`）时不插，别压在游戏上。
- 顺手修 `_reflow` 用**收起**高度给**展开**的一摞摆位、下面那张叠上去的问题（排查时在实机 z 序里直接看到）。

## 二、修改文件说明

| 文件 | 改了什么 | 为什么 |
|---|---|---|
| `pet/notification_toast.py` | 新增 `raise_topmost(card)`（Windows：`_fs_user_busy_state` 放行后 `_set_windows_topmost(hwnd, True)`）；`ToastStack.__init__` 多 `topmost=` 注入点与 `_watch` QTimer（`_TOPMOST_EVERY_MS=2000`）；`_reflow` 末尾调 `_assert_topmost()` 并在有卡片时启动看门狗；`_assert_topmost` 按老 → 新重插、没卡片就停；`_reflow` 的高度列表改用 `card_height(e.notices, e.card.expanded)`；模块 docstring 补一条「置顶要自己守」 | 见核心特性 |
| `tests/test_notification_toast.py` | 三条新测试：重排时按老 → 新重插（一张走了再插剩下的）；看门狗在场时反复插、没卡片就停；展开后下面那张按展开高度让位 | 红 → 绿 |

### 未改动

- 卡片的建法、动画、点击 / 划走 / 展开语义、设置项；`platform_win` 的两个函数原样复用。

## 三、实现要点

- 重插顺序：`_entries` 是最新在前，重插时 `reversed` → 最旧先插、最新最后插，于是 topmost 带里最新的在最上，
  和「贴着角的是最新」一致；卡片互不重叠时带内先后肉眼看不出。
- 看门狗只在 `visible_cards()` 非空时跑；`_assert_topmost` 发现没有在场卡片就 `stop()`。正在退场（`leaving()`）的卡不插。
- 真全屏时不插：和 `_on_notifications_arrived` 的「全屏不弹」同一个判定函数 `_fs_user_busy_state`（只认 QUNS 3 / 4；
  QUNS_BUSY=2 不算——本机最大化的 Electron 窗口就会让它报 2，恰恰是这次的触发条件，见下）。

## 四、性能分析

- **稳态**：没有卡片在场时零开销（看门狗停着）。有卡片时每 2 s 一轮：`SHQueryUserNotificationState` 一次 + 每张卡一次
  `SetWindowPos(NOMOVE|NOSIZE|NOACTIVATE)`。实测（本机，`QT_QPA_PLATFORM=windows`，各 500 次取均值）：
  `SHQueryUserNotificationState` 88.0 µs / 次，`SetWindowPos(HWND_TOPMOST)` 23.9 µs / 次，`raise_topmost` 整体 150.9 µs / 次
  → 10 张卡满额时约 1.5 ms / 2 s ≈ 0.08 % 的一个线程。
- **新增路径**：每次 `_reflow`（弹出 / 走掉 / 展开 / 同来源更新）多一轮同样的调用，触发频率等于通知频率（今天 13:07–14:02
  共 26 次弹出）。
- **系统调用 / 线程 / 内存**：两个 user32 / shell32 调用，GUI 线程里同步执行（都是微秒级）；没有新线程、网络、磁盘；
  一个 `QTimer` 对象，常驻内存可忽略。`SetWindowPos` 带 `SWP_NOMOVE|SWP_NOSIZE` 不触发重排重绘。

## 五、实机运行记录

本机 Windows 11、三屏（主屏 3072×1280 逻辑 / 125 %），桌宠从源码跑（`run.bat`）。

1. **现象**（用户截图 14:00:38）：主屏右上四张卡、大片空白、底下一张；日志 14:00:34–14:02:06 之间没有新弹出。
2. **排除**：离屏 + 真实窗口各复现一遍「中间三张到期 / 交错到期 / 同来源更新时别的卡在动」，补位全部正常；
   今天通知中心里 23 条真实通知按实机规则分 12 组逐组渲染（收起 / 展开），`_render` 无一抛错；GDI / USER 对象 131 / 134
   （上限 10000）；三张「看不见」的窗口 `DwmGetWindowAttribute(CLOAKED)=0`、`IsWindowVisible=True`、`WS_EX_TOPMOST` 位在。
3. **定位**：枚举桌宠进程的顶层窗口——8 张卡片窗口都在、位置就是 `stack_positions` 算出来的那 8 个槽；屏幕抓图里只画出
   5 张；`WindowFromPoint` 在另外 3 张中心点返回的是一个**最大化的 `Chrome_WidgetWin_1`（VS Code）**；完整 z 序链里它
   （非置顶）排在 #106，三张卡排 #246 / #250 / #251——卡片掉到了普通窗口下面。`SHQueryUserNotificationState()` 此时报
   `QUNS_BUSY(2)`：Windows 把那个最大化窗口当全屏，它一被激活就压到置顶带之上，之后再**显示**的卡才又在它上面——
   所以哪几张看不见是「随机」的。一张 14:00 还看得见的卡（后来被用户展开过）到 14:20 也被盖住了，证明不是新建时的问题。
4. **验证修法**：对实机那 5 张卡从外部 `SetWindowPos(HWND_TOPMOST)`（从底到顶）→ 全部回到 z 序 #33–#37，VS Code #134，
   立刻可见。
5. **修后实机**：桌宠重启到带本修复的代码（本地分支 cherry-pick，pid 18904），等到真实通知弹出 2 张后，从外部把它们压到
   `HWND_BOTTOM`：0.5 s / 1.0 s 仍在下面，**1.5 s 回到最大化窗口之上**（看门狗 2 s 周期）。用修复后的代码另起进程弹 3 张
   真实窗口做同样的事：1.50 s 回来。日志 0 条非噪音错误。
6. **没法自动的部分**：让 Windows 真的把一个激活的最大化 Electron 窗口压到桌宠卡片之上——在测试进程里用
   `SetForegroundWindow` 激活它复现不出来（卡片仍在上面），这个压制只在长时间运行的桌宠进程里观察到；所以修法不赌
   触发条件，而是周期性把在场的卡插回去，上面第 5 条就是用「人为压到最底」代替触发条件做的验证。

## 六、测试与验证

- 红 → 绿：`test_reflow_reasserts_topmost_oldest_first_newest_last`（修前 `[] == [1, 2, 3]`）、
  `test_topmost_watchdog_runs_while_cards_are_shown_and_stops_after`（修前 `AttributeError: _watch`）、
  `test_reflow_uses_expanded_height_so_the_card_below_does_not_overlap`（修前 `174 == 220`）。
- `ruff check` 过；`tests/test_notification_toast.py` + `tests/test_architecture.py` 39 条全过。
- 全量：见本文末「数字」。

## 七、已知限制与后续

- 看门狗 2 s 一轮：被盖住后最多 2 s 才回来；要更快可以调 `_TOPMOST_EVERY_MS`，代价成比例。
- 真全屏（QUNS 3 / 4）期间不插，退出全屏后下一轮看门狗再插回；`QUNS_BUSY(2)` 不拦（本机最大化 Electron 就是 2，
  拦了等于修不了）。
- 没做「监听前台窗口变化事件」（`SetWinEventHook(EVENT_SYSTEM_FOREGROUND)`）：桌宠已有一个前台 / 全屏轮询，再挂一个钩子
  不值；周期重插够用。

## 八、风险与回滚

- 风险：重插把卡片抬到**其他置顶窗口**（本进程聊天窗 / 设置窗、第三方置顶工具）之上——它们在卡片的角落位置重叠时会被卡片
  压住；卡片几秒就走或可划掉，可接受。
- 回滚：revert 这一个提交；没有数据 / 配置格式变化。

## 数字

| 文件 | +/− |
|---|---|
| `pet/notification_toast.py` | 42 / 2 |
| `tests/test_notification_toast.py` | 46 / 0 |
| `docs/PR-REPORT-TOAST-TOPMOST-2026-11-02.md`（新）、`docs/INDEX.md` | — |

全量测试（隔离 worktree、`QT_QPA_PLATFORM=offscreen`、临时 `APPDATA`）：待填。
