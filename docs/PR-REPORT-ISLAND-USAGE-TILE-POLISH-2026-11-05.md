# PR 报告：灵动岛用量磁贴打磨 + 仪表盘透明底 + 置顶看门狗（2026-11-05）

> **基线**：`390af73e`（main，Merge PR #14「列队」）
> **分支**：`feature/island-usage-tiles-polish`　**日期**：2026-11-05
> **范围**：14 个文件（实现 7、测试 6、文档 1 + `INDEX.md` 登记）
> **关联**：同日的任务栏停靠修复 `PR-REPORT-ISLAND-DOCK-TASKBAR-2026-11-05.md`（PR #21，独立分支）；
> 通知卡片的置顶看门狗 `PR-REPORT-TOAST-TOPMOST-2026-11-02.md`（本次岛的看门狗与它同口径，但多了「真被盖住才插」）；
> 分账号用量 `PR-REPORT-ISLAND-USAGE-TWO-ACCOUNTS-2026-11-02.md`

## 一、核心特性

用户一次提了五点（原话顺序）：用量那块磁贴太长、鼠标一动倾斜得厉害；去掉「今日」；「Win」换
Windows 图标、「WSL」换 Ubuntu 图标；仪表盘背景透明让每张卡片突出、加阴影；岛要总在最上。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 倾斜按尺寸限幅 | `metro_tilt_params(rect)`：角度按磁贴长边 / 28 反比缩小、透视视点等比拉远。原来 24° 套在 150px 宽的磁贴上，光标压右缘时左缘要挪出 **26.6px**；限幅后 **1.1px**，与 28px 方块（1.9px）相当 |
| 2 | 不写「今日」 | `usage.headline` / `usage.headline.multi` / 占位 `island.usage.placeholder` 三条文案（中 / 英）去掉前缀；悬停说明里的「今日 Claude Code 用量 …」保留 |
| 3 | 账号换记号 | 监视器多发一份 `[(账号键, 短名, 数字)]`；Metro 下 `windows` → 四格窗、`wsl` → Ubuntu 一环三点（`context_menus.icons` 已有的手绘记号，颜色跟磁贴文字）；不认识的账号键画「短名 数字」；别的样式（没有磁贴可画记号）照旧画整段文字 |
| 4 | 仪表盘透明底 + 阴影 | 窗口 `WA_TranslucentBackground`，四张磁贴直接浮在桌面上，每张底下四层半透明黑阴影（外扩 1/3/5/8px）；页头 / 页脚 / 状态文字换 `_HaloLabel`：反色光晕（深字白晕、浅字黑晕），深浅壁纸都读得出 |
| 5 | 置顶看门狗 | 岛可见期间 2 s 一轮：z 序里真有**别的进程**的可见窗压着才 `SetWindowPos(HWND_TOPMOST)`；真全屏（QUNS 3/4）或系统外壳的面（开始菜单 / 任务栏弹出层）在前台时歇着；本进程的窗（通知卡片 / 仪表盘 / 气泡）不算盖住。实机：外来置顶窗盖上去 **1.76 s** 后岛回到最上 |

**红线 / 不变量**：
- 无新配置键；`usage_changed` 信号从 `(str, str)` 变成 `(str, str, object)`，唯一的接收方 `DynamicIsland.set_usage_info` 同步加了可选参数，旧调用（两个参数）仍可用。
- 28px 方块磁贴的倾斜参数原样不动（`metro_tilt_params` 对长边 ≤ 28 的矩形返回原值）。
- 岛的事件驱动置顶（`reassert_topmost` 的 popup / `coversIsland` 两条让路规则）不变，看门狗只是多一个触发点，且走同一个入口。
- 通知卡片的看门狗不受影响：岛不把自家的卡片当「盖住」，两边不会每 2 s 互相压一次（见「三、实现要点」里的实机发现）。

## 二、修改文件说明

`git show --numstat HEAD`（提交 `2a660c26`）：

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/dynamic_island.py` | +146 / −11 | ① `metro_tilt_params` 纯函数 + `metro_tilt` 改用它；② 账号记号：`_ACCOUNT_GLYPHS` 映射、`_usage_segments` 状态、`set_usage_info(text, detail, segments)`、`usage_segment_glyphs()`（公开给测试 / 布局）、`_usage_block_width()`（磁贴宽：记号 14px + 3px 缝 + 数字，账号之间 10px）、`_glyph_pixmap()`（按 (记号, 颜色, DPR) 缓存）、`_paint_usage_segments()`；`_metro_layout` 的用量块宽与 `_paint_metro_block` 的用量分支接上；内容层缓存键加 `_usage_segments`；③ 占位表 `_PLACEHOLDER_KEYS` 的「今日 --」→「--」；④ 看门狗：`_topmost_watch` QTimer（2 s，`showEvent` 启 / `hideEvent` 停）、`_watch_topmost()`、`_native_occluder()`、模块级 `_native_topmost_hold_off()`；探测与让路都是可注入的实例属性（测试换假 z 序） |
| `pet/platform_win.py` | +94 / −0 | 新增一节「置顶看门狗」：自备一份 `user32`（`_z_user32`，HWND 按指针声明，不改进程共享那份的 argtypes）；`_window_info(hwnd)` → (可见, cloaked, 屏幕矩形, 类名, 本进程的)；`_prev_window`；`occluder_above(hwnd, rect, prev=, info=)` 纯逻辑可注入；`topmost_hold_off()`（`_fs_user_busy_state` + 前台窗口类名在 `_SHELL_SURFACE_CLASSES` 里） |
| `pet/usage_dashboard_ui.py` | +70 / −10 | `_TILE_SHADOW_LAYERS` / `TILE_SHADOW_SPREAD`、`halo_color()`、`_HaloLabel`（字号 / 字重 / 字距由代码给，`set_ink` / `ink` / `halo`，paintEvent 四周 1px + 下方 2px 画光晕再画字）；窗口 `WA_TranslucentBackground`、样式表底色 `transparent`、四个文字标签换 `_HaloLabel`、`apply_theme` 给它们上色；新 `paintEvent` 在每张磁贴底下画阴影 |
| `pet/claude_usage.py` | +8 / −1 | `headline_segments(accounts)`：两个账号起返回 `[(键, 短名, 数字)]`，一个账号返回空；`headline` 的 docstring 改成现在的文案 |
| `pet/claude_usage_monitor.py` | +3 / −2 | `usage_changed = Signal(str, str, object)`；`_on_measured` 把分段一起发 |
| `pet/locale/zh.json` / `en.json` | +3 / −3 各 | 三条文案去掉「今日」/「Today」前缀 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_island_usage_polish.py` | +252（新增） | 倾斜：方块原值；宽 / 高磁贴角度与长边成反比；原参数套在宽磁贴上边缘挪 > 20px、限幅后 ≤ 方块 + 0.5px；真岛上宽磁贴悬停边缘 < 2px。文案：三种 headline 无「今日」、detail 仍有。分段：两账号 / 读不到 / 单账号；监视器发三元组；Metro 磁贴画记号（`usage_segment_glyphs` == `[("windows", …), ("ubuntu", …)]`，比画「Win / WSL」字样窄，不认识的键退回短名）；非 Metro 不画记号。仪表盘：底色 alpha 0、磁贴内像素是磁贴色、正下方 2px 半透明、再远透明；光晕颜色随字色反色、`ink()` 跟主题。看门狗：只在可见时跑、2000ms；没人盖不重申、盖了重申、外壳在前台不重申；`occluder_above` 对假 z 序：自家窗 / 不可见 / cloaked 都不算，相交的外来窗算 |
| `tests/test_island_info_slot.py` | +5 / −5 | 占位「--」；两个 emit 补第三个参数；文案去「今日」 |
| `tests/test_claude_usage.py` | +5 / −5 | 五处 headline 断言去「今日」（detail 的断言不动） |
| `tests/test_claude_usage_monitor.py` | +7 / −7 | 槽函数收三个参数；五处 headline 去「今日」 |
| `tests/test_island_english.py` | +1 / −1 | 占位「Today --」→「--」 |
| `tests/test_usage_dashboard.py` | +3 / −1 | 主题切换测试：原来断言 (4,4) 像素是页面底色，现在底色透明，改成「alpha 0 + 标题字色跟主题」 |

### 未改动

- 仪表盘磁贴里的大数字「Win 2.38M · WSL 1.10M」和图例「■ Win … · □ WSL …」仍是文字：`Tile` 是纯字符串的数据类，
  用户这次说的是岛上那块磁贴；要换也是单独一轮。
- `pet/notification_toast.py` 的看门狗没动（它每 2 s 无条件插，岛这边的「真被盖住才插」没有反向移植）。
- `_METRO_TILT_DEG` / `_METRO_TILT_DISTANCE` 数值不变。

## 三、实现要点

- **倾斜限幅的数学**：`tilt_transform` 是绕中心的透视旋转，边缘位移 ≈ 半边长 × (1 − cosθ) 再除以透视项
  (1 ∓ 半边长·sinθ / 视距)。半边长从 14 变成 75，同一个 θ 位移放大五倍还多，透视项更是从 0.07 变成 0.38
  （所以用户看到的是整块乱晃）。角度按长边反比缩、视距等比拉远，两项都回到方块的量级。
- **记号走现成的图标语言**：`context_menus.icons` 里早有 `windows`（四格窗）和 `ubuntu`（一环三点，正是
  `host_icons` 给 WSL 的手绘回退），单色、跟字色，和岛上别的磁贴图标一个风格；没有引入品牌色或位图资源。
- **分段而不是解析文案**：岛不去拆「Win 2.38M · WSL 1.10M」这个字符串，监视器把结构化的分段一起发出来；
  文案仍然照发，给非 Metro 样式和悬停提示用。
- **看门狗为什么要「真被盖住才插」**：探针第一次跑在改之前的岛上就发现它正被**自家的通知卡片**压着
  （卡片有自己的 2 s 看门狗）。要是岛也每 2 s 无条件插，两边就轮流把对方压下去。于是 `_window_info`
  多了一位「本进程的」，自家窗一律不算；另外不可见 / 被 DWM cloaked 的窗也不算（UWP 的后台窗常年 cloaked
  却在 z 序里）。没人盖着时一次 `SetWindowPos` 都不发。
- **自备一份 `user32`**：`ctypes.windll.user32` 是进程共享的，给 `GetWindow` 设 `restype=HWND` 会影响
  别处按 int 用它的代码；`ctypes.WinDLL("user32")` 另起一份只在这一节用。
- **备选**：① 用 `WinEventHook(EVENT_SYSTEM_FOREGROUND / EVENT_OBJECT_REORDER)` 事件驱动——要常驻一个
  消息钩子且 REORDER 事件极密，不值；② 继续靠 30 s 心跳——用户的原话是「总在最上」，30 s 太久。

## 四、性能分析

**方法（可复现）**：`timeit` 200 000 次 / 调用（纯函数，`QT_QPA_PLATFORM=offscreen`）；原生调用
在真实 `windows` 平台上对正在跑的岛窗口各 300 次取均值。Python 3.13.15，Windows 11 10.0.26300，
三块 125% 屏。

| 指标 | 实测 | 归属 |
|---|---|---|
| `metro_tilt_params` | 0.18 µs / 次 | 新增（悬停磁贴每帧一次） |
| `halo_color` | 0.40 µs / 次 | 新增（标签重绘时） |
| 仪表盘整窗渲染（`grab()`，含 16 块阴影矩形 + 4 个光晕标签） | 1.22 ms / 帧 | 既有路径加重；仪表盘只在打开时、悬停柱子才重绘 |
| `occluder_above(岛 hwnd)`（真 z 序，岛上面 10 来个 topmost 窗） | 29.5 µs / 次 | 新增，每 2 s 一次 |
| `topmost_hold_off()`（`SHQueryUserNotificationState` + 前台类名） | 88.2 µs / 次 | 新增，每 2 s 一次 |
| 看门狗一轮合计（没被盖住） | ≈ 118 µs / 2 s ≈ 0.006 % 单核 | 稳态 |
| 看门狗一轮（被盖住，多一次 `SetWindowPos`） | + 23.9 µs（沿用通知卡片报告的实测） | 只在被盖住的那一轮 |

**结论**：① 稳态：岛每 2 s 多 ≈ 118 µs 的两次 user32 / shell32 调用，无 `SetWindowPos`；paint / 动画 /
碰撞路径没有新代码。② 新增路径：倾斜参数 0.18 µs（悬停时每帧）、记号位图按 (记号, 颜色, DPR) 缓存只画一次、
仪表盘每帧 1.22 ms 且只在打开 + 悬停时重绘。③ 没有新线程 / 网络 / 磁盘；多一个 `QTimer`。④ 内存：记号
位图缓存最多（2 记号 × 几种字色 × DPR 数）张 14px 位图，可忽略；`_HaloLabel` 替换同数量的 `QLabel`。

## 五、实机运行记录

本机：Windows 11，主屏 Dell AW3821DW 3840×1600 @125%，底部任务栏；桌宠从合并了本分支与 PR #21 的
本地运行分支 `local/run-island-2026-11-05`（工作区 `.claude/worktrees/island-run`）起，pid 51004，14:52。

**启动**：

```
2026-11-05 14:52:29 acquired pid=51004 lock=...\overlay-instance.lock
2026-11-05 14:52:29,811 INFO big-fat-fish 启动 (slot: 0, instance: )
2026-11-05 14:52:30,935 INFO 进入事件循环
（无 WARNING / ERROR）
```

**岛上的记号（真机截图，`QScreen.grabWindow(0)` 截岛所在区域）**：胶囊从左到右是头像、「BigFatFish」、
用量磁贴「⊞ 1.84M  ◌ 128.2K」（四格窗 + Ubuntu 一环三点，没有「今日」、没有「Win / WSL」字样）、
「2 工作中 4 休息中」、链接 / 简报 / 个人助理 / 铃铛四块。岛窗口物理宽从 719px（改前，带「今日 Win … · WSL …」）
变成 598px。截图里带着壁纸上的别的内容，只留在会话草稿目录，不入库。

**看门狗（探针 `probe_cover.py`，另一个进程）**：在岛的矩形上盖一个外来的无焦点置顶窗，然后每 0.25 s 看
岛在不在它上面：

```
pet pid 51004 island hwnd 527748 rect(physical) (2633, 843, 598, 55)
t=0.0s probe shown; island above probe? False
timeline (t, island above probe): [(0.25, False), (0.5, False), (0.75, False), (1.0, False), (1.26, False),
                                   (1.51, False), (1.76, True), (2.01, True), (2.26, True), ...]
island back on top after 1.76 s
--- pet log:
2026-11-05 14:53:46,813 INFO 灵动岛被 Qt6120QWindowToolSaveBits 盖住，重新置顶
```

**改之前的现场（同一探针对改前的岛，pid 51508）**：`occluder_above(岛)` 返回 `Qt6120QWindowToolSaveBits`
——岛正被自家的通知卡片（x 3370–3820、y 421–556）压着一角；这就是「本进程的窗不算盖住」的来历。

**边界与失败路径**：
- 探针自己的进程里调 `occluder_above(岛)` 返回 `''`（探针窗是「本进程的」，被排除）——同一规则的另一面。
- 真全屏 / 开始菜单在前台时不插：`topmost_hold_off()` 在本机此刻（前台是 Chrome）返回 False；真全屏路径沿用
  通知卡片报告里验证过的 `_fs_user_busy_state`。
- 仪表盘的透明底与阴影在真机上**未截图**：打开它要点岛上的数字，本会话没有做桌面自动化（要用户批准对桌宠窗口
  的控制）；离屏渲染（浅色主题贴深 / 浅底、深色主题贴浅底三张）看过：底透明、磁贴阴影可见、页头文字有光晕。
  待用户点开确认。
- 岛上记号的字号 / 对齐在 125% 下看过真机截图；100% / 150% 未验。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests scripts` | All checks passed |
| 聚焦（红） | `pytest -q tests/test_island_usage_polish.py`（改实现前） | ImportError `headline_segments` / `metro_tilt_params`（收集即红） |
| 聚焦（绿） | `pytest -q tests/test_island_usage_polish.py tests/test_usage_dashboard.py tests/test_island_info_slot.py` | 49 passed |
| 相关族 | `pytest -q tests/test_island_info_slot.py tests/test_claude_usage.py tests/test_claude_usage_monitor.py tests/test_island_english.py tests/test_usage_dashboard.py tests/test_island_metro.py tests/test_island_content_cache.py tests/test_first_batch_features.py tests/test_dynamic_island_revamp.py tests/test_dynamic_island_multiscreen_release.py tests/test_notification_toast.py tests/test_i18n.py tests/test_language_reload.py tests/test_island_usage_polish.py` | 182 passed（期间修掉一处漏改的「今日」断言） |
| 架构红线 / 报告纪律 | `pytest -q tests/test_claude_usage.py tests/test_architecture.py tests/test_pr_report_discipline.py` | 161 passed |
| 受影响族并发 3 份 | 三份 `pytest` 同时跑 `test_island_usage_polish / test_usage_dashboard / test_island_info_slot / test_claude_usage_monitor / test_island_metro` | 67 passed × 3（2.16 / 2.18 / 2.19 s） |
| 合并运行分支 | 在 `island-run`（本分支 + PR #21）跑 `test_dynamic_island_panel_edges / test_island_usage_polish / test_dynamic_island_revamp / test_usage_dashboard` + ruff | 62 passed，ruff 干净 |
| 全量 | `python -m pytest -q -p no:cacheprovider`（PowerShell 起，`APPDATA` 指到临时目录） | 见「全量结果」 |

## 七、已知限制与后续

- 仪表盘磁贴里的「Win / WSL」字样没换记号（见「未改动」）；要换需要把 `Tile.value` 从字符串改成分段。
- 看门狗只认「别的进程的可见窗」；第三方工具若把窗口 cloaked 后再显示（极少见）那一轮不算盖住，下一轮补上。
- 仪表盘透明底在真机上待用户点开确认；100% / 150% 缩放下的记号对齐未验。

## 八、风险与回滚

- 影响面：岛的用量磁贴（Metro）、仪表盘窗口外观、岛的置顶行为；肥鱼本体、碰撞、通知卡片不受影响。
- 配置：无新键；`usage_changed` 信号多一个参数（接收方已同步）。
- 回滚：`git revert 2a660c26`，无残留状态；本地运行分支 `local/run-island-2026-11-05` 与工作区
  `.claude/worktrees/island-run` 是为实机验证临时建的，合并后可删。
