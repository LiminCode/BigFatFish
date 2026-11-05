# PR 报告：灵动岛「靠边半隐藏」不再把任务栏上沿当屏幕边缘（2026-11-05）

> **基线**：`390af73e`（main，Merge PR #14「列队」）
> **分支**：`fix/island-dock-skip-panel-edges`　**日期**：2026-11-05
> **范围**：6 个文件（实现 1、文案 2、测试 2、文档 1 + `INDEX.md` 登记）
> **关联**：灵动岛四边停靠的来历见 `tests/test_dynamic_island_revamp.py`；
> 跨屏松手选屏（issue #154）见 `tests/test_dynamic_island_multiscreen_release.py`

## 一、核心特性

用户反馈：岛的「靠近桌面边缘自动隐藏」在任务栏边上也起效，没法把岛**放在任务栏
上面**。根因可测量：停靠判定、细条位置、夹屏全部按 `screen.availableGeometry()`
（工作区）算，Windows 底部任务栏把工作区顶上去 48px，任务栏的上沿就成了"屏幕
底边"——岛拖到任务栏上方 40px 内就被收成 16px 细条贴在任务栏上沿（实机日志
`14:12:27 … bottom=12 → dock=bottom`、`14:22:11 … bottom=0 → dock=bottom`）。

修法：**只有工作区边与物理屏边重合的那几边才可停靠**。被任务栏 / 系统面板顶进来
的那一边不参与就近判定，岛贴着它松手就以完整胶囊停在工作区边上（底边正好贴任务栏
上沿）。启动 / 刷新配置时，存着的停靠边若落在这样的边上（本修法之前存下的、任务栏
换了边、岛换到别的屏），按"不停靠"复位并落盘。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 任务栏那一侧不停靠 | `dockable_edges(available, screen_rect)`：工作区比物理屏向内缩进 ≥ 8px 的边视为被面板占住 |
| 2 | 其余三边照旧 | 顶 / 左 / 右（主屏实测）仍然 40px 内收细条、悬停滑出，行为与数值不变 |
| 3 | 旧状态自愈 | `_apply_position` 发现存着的 `dock_edge` 不可停靠 → 写回 `none`、细条形态复位 |
| 4 | 日志可诊断 | 松手日志多一段 `可停靠 left/right/top`，一眼看出哪条边被排除 |
| 5 | 设置页文案 | 「靠边半隐藏」说明改成现在的语义（中 / 英） |

**红线 / 不变量**：
- 没有新增持久化键；`dock_edge` 的取值集合不变（`none/top/bottom/left/right`）。
- 拿不到物理屏几何（`screen_rect is None`）时四边都算，等于旧行为。
- 「靠边半隐藏」总开关、悬停滑出、`_DOCK_BACK_MS`、碰撞体跳过停靠态等逻辑不动。
- 没有任务栏的屏（本机两块竖屏实测 inset 全 0）行为与改动前完全一致。

## 二、修改文件说明

`git show --numstat HEAD`（提交 `9d1a741c`）：

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/dynamic_island.py` | +55 / −3 | ① 新常量 `_PANEL_MIN_INSET = 8`；② 新纯函数 `dockable_edges(available, screen_rect, min_inset)`：按四边缩进量筛出可停靠边，`screen_rect is None` 时返回四边；③ `dock_edge_for` 新增关键字参数 `edges`，只在这些边里取最近者，空集返回 `"none"`；④ `DynamicIsland._dockable_edges(screen)` 静态方法把前两者接到 QScreen 上；⑤ `mouseReleaseEvent` 拖拽分支按当前屏算 `edges` 再判定，日志加 `可停靠 …`；⑥ `_apply_position` 开头检查存着的停靠边是否仍可停靠，不可则 `_save_dock_edge("none")` 并把 `docked` 形态复位为 `normal`（否则岛一启动就是贴任务栏上沿的细条） |
| `pet/locale/zh.json` | +1 / −1 | `settings.dlg.drag_any_screen_edge_top`：去掉"顶部被占时可停靠侧边"，改为"任务栏那一侧不算边缘，岛可以放在任务栏上面" |
| `pet/locale/en.json` | +1 / −1 | 同上英文 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_dynamic_island_panel_edges.py` | +214（新增） | 纯函数：四种工作区（无面板 / 底部任务栏 / 左侧任务栏 / 上下双面板）的可停靠边、`None` 回退、2px 误差不算面板；`dock_edge_for` 带 `edges` 的排除 / 就近落到相邻可停靠边 / 空集。真实松手路径（假屏 1920×1080，底部 48px 任务栏）：拖到任务栏上沿 → `normal`、`dock_edge=none`、胶囊底边 == 工作区底边、配置落盘 `none`；再拖到顶边 → 照常 `docked`。左侧任务栏对照：左边不停靠、底边仍停靠。启动路径：存着 `dock_edge=bottom` + 底部任务栏 → 启动即 `none` / `normal` / 落盘；对照存着 `top` → 照旧细条 |
| `tests/test_dynamic_island_multiscreen_release.py` | +4 / −0 | 假屏 `_FakeScreen` 补 `geometry()`（= 工作区，假屏没有任务栏），松手路径现在要比这两块几何 |

### 未改动

- `pet/config.py` 的 `dynamic_island` 清洗：键集合与取值集合没变，不需要迁移。
- `pet/island_collision.py` / `pet/island_bridge.py`：读的是 `dock_edge` 属性，语义不变。
- `strip_rect_for` / `_target_rect` / `_clamp_rect` 继续用 `availableGeometry()`：
  能走到这几处的边一定是工作区边 == 物理屏边，用哪个都一样。
- `pet/modern_settings_dialog.py`：没有新开关（见"七、已知限制"里为什么不做成设置）。

## 三、实现要点

- **判定依据是几何差，不是平台 API**。`QScreen.geometry()` 与 `availableGeometry()`
  的差就是系统预留区（Windows 任务栏、macOS 菜单栏 / Dock、MyDockFinder 之类
  AppBar），跨平台、不用猜任务栏在哪边。阈值 8px：任务栏 ≥ 40、菜单栏 24、第三方
  Dock ≥ 30 都远超；1~2px 的工作区误差不夺走一条边。
- **过滤放在判定之前而不是之后**。`dock_edge_for` 先把被占的边从 `distances` 里
  删掉再取最近者：岛贴在任务栏上沿同时靠右角时，就近落到 `right` 而不是因为 `bottom`
  最近而整体判 `none`——角落停靠体验与改前一致。
- **旧状态在 `_apply_position` 自愈**。这是启动与 `refresh_from_config` 的共同入口，
  而 `dock_edge` 属性本身不碰屏（它在 paint / 碰撞路径里被高频读取，不能在里面查
  QScreen）。复位时顺手把 `docked` 形态改回 `normal` + `_apply_fixed_size()`，
  否则窗口仍是 16px 高、再被夹回工作区底边。
- **备选方案**：① 做成设置项「任务栏一侧也停靠」——SETTINGS-CHANGE-GATES 要求
  新设置有明确用例，而"细条贴在任务栏上沿"没人要；② 只对 `bottom` 边特判——任务栏
  可以在四边任意一边，左侧任务栏对照测试就是为此。

## 四、性能分析

**方法（可复现）**：`timeit` 200 000 次 / 调用，`QT_QPA_PLATFORM=offscreen`，
Python 3.13.15，Windows 11 10.0.26300，屏 3840×1600、工作区 3840×1552。

| 指标 | 实测 | 归属 |
|---|---|---|
| `dockable_edges(avail, screen)` | 0.64 µs / 次 | 新增 |
| `dock_edge_for(rect, avail)`（旧） | 0.71 µs / 次 | 既有 |
| `dock_edge_for(rect, avail, edges=…)` | 0.90 µs / 次 | 既有 + 过滤 |
| 新判定路径合计 | 1.54 µs / 次（旧 0.71 µs，+0.83 µs） | 松手时一次 |
| 新增 Qt 调用 | 每次 `screen.geometry()` 1 次（松手 / 启动 / 刷新配置） | 新增 |
| 岛测试族（38 例） | 1.35 / 1.37 / 1.38 s，3 份并发 | 验证 |

**结论**：① 稳态开销无变化——paint / 动画 tick / 碰撞结算路径没有新代码，`dock_edge`
属性仍只读配置字典；② 新增路径 +0.83 µs 加 1 次 `QScreen.geometry()`，只在鼠标松手、
启动、设置保存时各跑一次，用户动作级频率；③ 没有新的线程 / 网络 / 磁盘——`_apply_position`
里的 `_save_dock_edge("none")` 只在"存着的边被占"这一次性状态下写一次配置文件，之后
不再触发；④ 内存无增长（一个 ≤ 4 元素的 frozenset，用完即弃）。

## 五、实机运行记录

本机：Windows 11，三块 125% 屏，主屏 Dell AW3821DW 底部任务栏。

**根因现场**（改动前、正在跑的桌宠 pid 34140 的日志 `%APPDATA%\big-fat-fish\pet-34140.log`）：

```
2026-11-05 14:12:27,459 INFO 灵动岛拖拽落点 (2065,1176)：距四边 top=1176 bottom=12 left=2065 right=492（阈值 40）→ dock=bottom
2026-11-05 14:22:11,566 INFO 灵动岛拖拽落点 (1822,1188)：距四边 top=1188 bottom=0 left=1822 right=681（阈值 40）→ dock=bottom
```

用户把岛放到任务栏上方（距工作区底边 12px / 0px），被判成 `bottom` 收成细条——这就是反馈的现象。

**前提探针**（真实 `windows` 平台，`QGuiApplication.screens()` + 本改动的 `dockable_edges`）：

```
Dell AW3821DW  geometry=(0, 0, 3072, 1280) available=(0, 0, 3072, 1232) dpr=1.25
               inset top=0 bottom=48 left=0 right=0 -> dockable=['left', 'right', 'top'] (min_inset=8)
DELL G3223Q    geometry=(3840, -995, 1728, 3072) available=(3840, -995, 1728, 3072) dpr=1.25
               inset top=0 bottom=0 left=0 right=0 -> dockable=['bottom', 'left', 'right', 'top'] (min_inset=8)
DELL S2721DGF  geometry=(6000, -207, 1152, 2048) available=(6000, -207, 1152, 2048) dpr=1.25
               inset top=0 bottom=0 left=0 right=0 -> dockable=['bottom', 'left', 'right', 'top'] (min_inset=8)
```

主屏底部缩进 48px（任务栏）→ 底边被排除；两块竖屏没有任务栏 → 四边照旧。

**重启到本分支**：结束 pid 34140（从主检出 main 起的），以本工作区为工作目录
`Start-Process .venv\Scripts\BigFish.exe -m pet`：

```
2026-11-05 14:23:00 acquired pid=51508 lock=...\overlay-instance.lock
2026-11-05 14:23:00,204 INFO big-fat-fish 启动 (slot: 0, instance: )
2026-11-05 14:23:00,917 INFO 素材加载完成：shenshen 106 段动画
（启动段无 WARNING / ERROR）
```

用户当前配置 `dock_edge: "none"`（已经把岛拖离了任务栏），所以启动时不走旧状态复位分支。

**用户可见行为的确认**：拖动需要真人操作，本会话没有做桌面自动化（需要用户批准
对桌宠窗口的控制权限）。待用户确认：把岛拖到任务栏上沿松手，预期岛以完整胶囊停在
任务栏上面、不收细条，日志出现
`灵动岛拖拽落点 …（阈值 40，可停靠 left/right/top）→ dock=none`；拖到顶边仍收细条。

**边界与失败路径**：松手假屏测试里"底部任务栏 + 右角"落到 `right`（不是 `none`）；
全边被占（`edges=frozenset()`）返回 `none`；`_FakeScreen` 没补 `geometry()` 之前多屏
松手测试会 `AttributeError`——这是为什么那 4 行要一起改。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests scripts` | All checks passed |
| 聚焦（红） | `pytest -q tests/test_dynamic_island_panel_edges.py`（改实现前） | ImportError `dockable_edges`（收集即红） |
| 聚焦（绿） | `pytest -q tests/test_dynamic_island_panel_edges.py tests/test_dynamic_island_revamp.py tests/test_dynamic_island_multiscreen_release.py` | 38 passed |
| 断言有效性 | 临时把 `_dockable_edges` 改回"四边都算"再跑新文件 | 3 failed（三个松手 / 启动用例）/ 3 passed（纯函数），恢复后 0 处残留 |
| 相关族 | `pytest -q tests/test_island_collision.py tests/test_island_bridge_velocity.py tests/test_island_chat.py tests/test_architecture.py tests/test_desktop_pet_features.py tests/test_pr_report_discipline.py tests/test_i18n.py tests/test_language_reload.py` | 2 failed：`test_image_directory_picker_opens_right_drawer_with_three_column_masonry`（基线，路径 > 260）、`test_modern_context_menu_has_compact_semantic_groups`（在未改动的 main 检出 `390af73e` 上同样失败，与本改动无关） |
| 岛测试族并发 3 份 | 三份 `pytest` 同时跑同一组 38 例 | 38 passed × 3（1.35 / 1.37 / 1.38 s） |
| 全量 | `python -m pytest -q -p no:cacheprovider`（PowerShell 起，`APPDATA` 指到临时目录） | **6 failed, 5941 passed, 14 skipped in 497.87s**。6 个都不是本分支的：4 个环境基线（`test_image_directory_picker_opens_right_drawer…`、`test_festival_id_guard_survives_optimize`、`test_real_second_process_refused_on_overlay_topology`、`test_capture_window_rect_coordinates_and_clamping`）+ `test_host_icons_are_warmed_at_the_cards_size`（main 上原样失败）+ `test_modern_context_menu_has_compact_semantic_groups`（main `390af73e` 上同样红） |

## 七、已知限制与后续

- **自动隐藏的任务栏**：Windows 对自动隐藏任务栏不预留工作区（工作区 = 全屏），
  底边会照常可停靠，细条会贴在任务栏弹出带上——与改动前一致，没有人反馈，先不动。
- **没有做成设置项**：被面板占住的边停靠成细条没有用例；真有人要再按
  `docs/SETTINGS-CHANGE-GATES.md` 加开关。
- **实机拖拽确认**待用户：见"五"。

## 八、风险与回滚

- 影响面：只有灵动岛的停靠判定与启动时的停靠边校验；肥鱼本体、碰撞、通知不受影响。
- 配置：无新键。`_apply_position` 可能把旧配置里的 `dock_edge` 从 `bottom`（或别的被占
  边）改成 `none` 落盘——这是期望行为；回滚代码后用户再拖一次即可重新停靠。
- 回滚：`git revert 9d1a741c` 即可，无残留状态；多屏假屏多出的 `geometry()` 随之撤掉。
