# PR 报告：灵动岛可以盖在任务栏正上方（2026-11-05）

> **基线**：`d7d82bec`（main，Merge PR #21「任务栏那一侧不算屏幕边缘」）
> **分支**：`fix/island-over-taskbar`　**日期**：2026-11-05
> **范围**：4 个文件（实现 1、测试 1、文档 1 + `INDEX.md` 登记）
> **关联**：`PR-REPORT-ISLAND-DOCK-TASKBAR-2026-11-05.md`（PR #21：任务栏那一侧不停靠）；
> `PR-REPORT-ISLAND-USAGE-TILE-POLISH-2026-11-05.md`（PR #22：含置顶看门狗，岛压在任务栏上要靠它保持在最上）

## 一、核心特性

PR #21 之后岛能**贴着**任务栏上沿停，但用户要的是**盖在任务栏正上方**（和任务栏重叠）。根因可测量：
岛的三处「夹回屏幕」（`_clamp_rect` / `_clamp_to_screen` / 拖拽松手）都按 `availableGeometry()`（工作区）算，
岛的任何一部分进了任务栏那一条就被推回去——实机把岛原生挪到任务栏上，不到 5 s 就被推回到任务栏上沿
（见「五」）。

修法：夹取按**整块物理屏幕**（`_placement_bounds(screen) = screen.geometry()`）。岛是置顶窗，盖在任务栏上面
由 PR #22 的看门狗保持在最上（任务栏 `Shell_TrayWnd` 在前台时让路，之后再回来）。停靠判定仍按工作区
（`dockable_edges` 已把任务栏那一侧排除），两者不冲突。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 岛可以拖进任务栏区域 | 松手 / 心跳 / 动画目标三处夹取都按物理屏，岛可以整个压在任务栏上，最远到屏幕物理底边 |
| 2 | 任务栏在任何一边都一样 | 左侧任务栏的对照测试：岛可以夹到物理屏左边 |
| 3 | 停靠不变 | 被任务栏占住的边仍不停靠；其余边的 40px 停靠阈值、细条、滑出都不动 |

**红线 / 不变量**：无新配置键；没有任务栏的屏（物理屏 = 工作区）行为与改动前完全一致；默认落点
（没存过位置时的右上角）仍按工作区算。

## 二、修改文件说明

`git show --numstat HEAD`（提交 `8f1820c9`）：

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/dynamic_island.py` | +18 / −8 | 新静态方法 `_placement_bounds(screen)`（返回 `screen.geometry()`，docstring 说明为什么是整块屏）；`_clamp_rect`、`_clamp_to_screen`、`mouseReleaseEvent` 的拖拽分支三处夹取改用它（松手处原来用 `available` 变量夹，现在 `available` 只给停靠距离用） |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_dynamic_island_panel_edges.py` | +19 / −9 | `test_drop_onto_the_taskbar_stays_there_without_docking`（原「停在任务栏上沿」改写）：松手时岛一半压在任务栏上 → 不推回、不停靠；再拖到屏幕底 → 夹在物理屏内、整个岛都在任务栏那一条里、不停靠。左侧任务栏对照：拖出屏外 → 夹到物理屏左边。旧停靠边复位后留在任务栏上沿那一带、不推回工作区。改前（main 的夹取）3 个用例红，改后绿 |

### 未改动

- `dockable_edges` / `dock_edge_for` / `strip_rect_for` / `_target_rect` 的停靠几何：仍按工作区。
- `_apply_position` 的默认落点：仍按工作区右上角。
- 多屏假屏（`test_dynamic_island_multiscreen_release.py`）物理屏 = 工作区，用例不需要改。

## 三、实现要点

- 只换夹取的参照矩形，不碰停靠：停靠边的判定在 #21 已经改成「工作区边与物理屏边重合的边才算」，
  岛压在任务栏上时离工作区底边的距离是负的（取绝对值后大于 40），本来也不会停靠。
- 松手路径原来把 `available` 同时用于夹取和停靠距离，现在拆开：夹取用 `bounds`，距离仍用 `available`。
- 为什么不是设置项：盖不盖任务栏由用户拖到哪决定，夹取只是不再阻止；没有人需要「禁止盖任务栏」。

## 四、性能分析

**方法**：改动只是把三处夹取读的矩形从 `availableGeometry()` 换成 `geometry()`，同一个 `QScreen` 上的
两个几何读取开销同级（Qt 都是缓存值的拷贝）；没有新路径、新调用、新定时器。`timeit` 200 000 次：
`screen.geometry()` 0.32 µs / 次，`screen.availableGeometry()` 0.38 µs / 次（`QT_QPA_PLATFORM=offscreen`，
Python 3.13.15，Windows 11）。

**结论**：① 稳态无变化；② 没有新增路径；③ 没有新系统调用 / 线程 / 磁盘；④ 内存无变化。

## 五、实机运行记录

本机：Windows 11，主屏 3840×1600 @125%，底部任务栏 60 物理像素（工作区底边 1540，屏幕底边 1600）。
探针 `probe_taskbar.py`（另一个进程）：用 `SetWindowPos` 把岛原生挪到「底边 = 屏幕物理底边」，然后每 5 s
看一次岛的矩形，40 s 后把它挪回原位。

**改前（正在跑的桌宠 pid 49812，旧夹取）**：岛本来停在任务栏上沿（y 1485–1540）；挪到 1545 后第一次采样
（5 s）就已被推回：

```
rect(physical) (2479, 1485, 598, 55) | screen phys bottom 1600 taskbar top 1540
samples (t, top, bottom): [(5, 1485, 1540), (10, 1485, 1540), ... (40, 1485, 1540)]
final rect (2479, 1485, 598, 55) -> overlaps taskbar: False | pushed back: True
```

**改后（从合并了本分支 + #22 的 `local/run-island-2026-11-05` 重启，pid 46520，15:43，启动无 WARNING / ERROR）**：

```
samples (t, top, bottom): [(5, 1545, 1600), (10, 1545, 1600), ... (40, 1545, 1600)]
final rect (2479, 1545, 598, 55) -> overlaps taskbar: True | pushed back: False
```

岛整个压在任务栏上 40 s（跨过 30 s 的 `_refresh` 心跳夹取）没被推回；真机截图：岛盖在任务栏图标行上，
胶囊下沿与屏幕底边齐。截图留在会话草稿目录，不入库。探针结束把岛挪回了原位（位置只在拖拽松手时落盘，
探针没有改配置）。

**边界与失败路径**：
- 拖拽松手那条路径探针没走（它是原生挪窗 + 心跳夹取），由同一个 `_placement_bounds` 决定，离屏测试覆盖；
  用户真拖一次即可确认。
- 岛压在任务栏上时点任务栏：`Shell_TrayWnd` 成为前台，看门狗让路，任务栏在上；焦点离开后下一轮看门狗
  （≤ 2 s）把岛插回最上。这一条没有在真机点过。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests scripts` | All checks passed |
| 聚焦（红） | `pytest -q tests/test_dynamic_island_panel_edges.py`（换回 main 的 `dynamic_island.py`） | 3 failed（压任务栏 / 左侧任务栏 / 旧停靠边复位）, 3 passed |
| 聚焦 + 相关族 | `pytest -q tests/test_dynamic_island_panel_edges.py tests/test_dynamic_island_revamp.py tests/test_dynamic_island_multiscreen_release.py tests/test_island_collision.py tests/test_island_bridge_velocity.py tests/test_usage_dashboard.py tests/test_island_info_slot.py tests/test_architecture.py` | 123 passed |
| 合并运行分支 | `island-run`（本分支 + #22 + #21）跑 `test_dynamic_island_panel_edges / test_island_usage_polish / test_pr_report_discipline` + ruff | 147 passed，ruff 干净 |
| 全量 | `python -m pytest -q -p no:cacheprovider`（PowerShell 起，`APPDATA` 指到临时目录） | FULLSUITE_ROW |

## 七、已知限制与后续

- 岛盖在任务栏上时任务栏那一段点不到（岛接管了那块的鼠标）；要点任务栏就把岛挪开或点岛以外的部分。
- 自动隐藏的任务栏没变（工作区 = 全屏，之前就能到底）。

## 八、风险与回滚

- 影响面：只有岛的位置夹取；停靠、看门狗、肥鱼本体不受影响。
- 配置：无新键；已存的位置照常使用。
- 回滚：`git revert 8f1820c9`，无残留状态。
