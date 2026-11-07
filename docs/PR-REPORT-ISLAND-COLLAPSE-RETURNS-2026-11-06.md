# PR 报告：灵动岛收起卡片回到展开前的位置（2026-11-06）

> **基线**：`e6e4361c`（Merge PR #24，灵动岛「消息记录」）
> **分支**：`fix/island-collapse-returns`　**日期**：2026-11-06
> **范围**：3 个文件（实现 1、测试 1、文档 1）
> **关联**：`PR-REPORT-ISLAND-MESSAGE-LOG-2026-11-06.md` 第七节「顺手发现、没修」；
> `PR-REPORT-ISLAND-OVER-TASKBAR-2026-11-05.md`（岛能盖在任务栏上，是本缺陷最常见的触发位置）

## 一、核心特性

用户 2026-11-06 下午报「岛不见了」。实机排查：桌宠进程活着、日志无 ERROR，岛窗口可见，
贴在主屏**顶边** y=0；当天用户把岛拖到任务栏上方（y=1236）三次，最后一次 15:52 拖到
(2058,108)，之后没有任何拖拽、隐藏或全屏记录，岛却到了 (1487,0)。

根因（真机量到）：展开后的卡片高 **1182** 逻辑像素（屏高 1280、工作区 1232）。
`expand_card` 的目标矩形经 `_clamp_rect` 夹屏时整块窗口被顶到 y=0；`collapse_card` 走
`_target_rect` 的普通分支，按**当前左上角 + 胶囊尺寸**放胶囊，于是胶囊留在卡片被顶到的
位置。岛只要不在屏幕最顶上那一截，展开一次就跑到顶边——看起来像消失了。这个缺陷
#24 的报告里已记下（当时卡片矮些、只是「下半屏」触发），现在消息记录框 + 会话历史
把卡片撑到接近整屏，触发面扩大到几乎任何位置。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 收起回原位 | 展开前记住胶囊左上角（`_rest_anchor`），收起时回到它（仍按屏幕夹一次），而不是留在卡片被顶到的位置 |
| 2 | 吞掉展开期间的位移 | 展开期间窗口被别的什么挪过（实机观察到 x 左移一截，机制未定，见第七节），收起同样回展开前的位置 |
| 3 | 拖拽 / 设置改位置不受影响 | 拖拽起手先收起再跟手（锚点随之作废）；卡片开着时设置页改 x/y，收起落在新位置 |

**红线 / 不变量**：停靠态（`dock_edge != none`）的展开 / 收回仍由 `_target_rect` 的停靠分支
决定，不记锚点；展开时卡片放不下仍被顶上去（卡片必须整块可见）；`_finish_animations`
仍把所有动画跳到终点。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/dynamic_island.py` | +23 / −2 | ① `__init__` 增 `_rest_anchor: QPoint \| None`；② `expand_card` 在把 `_mode` 改成 expanded 之前记下 `QPoint(self.pos())`（只在 normal 态记；docked 态置 None）；③ `collapse_card` 取出锚点并清空：normal 态且有锚点 → 目标 = `_clamp_rect(QRect(anchor, _rest_size()))`，否则沿用 `_target_rect()`；动画 / 直落两条路都用这个目标；④ `_apply_position` 在 expanded 态把锚点改成设置里的新位置（收起落在新位置，不回旧位置）；⑤ `_finish_animations` 先落到 `_geo_to`（几何动画终点）再按模式重算——终点不一定是「当前左上角 + 尺寸」，直接重算会把「回原位」丢掉（`showEvent` 与测试都走这里） |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_island_collapse_returns.py` | +142 / −0（新） | 假屏 1920×1040 驱动真实展开 / 夹取 / 收起代码，卡片高度给定 900：① 下半屏 (1200,900) 展开被顶上去、收起回到原矩形、模式回 normal；② 展开期间窗口被 `move` 过，收起仍回原位；③ 锚点已出屏时收起仍夹回屏内；④ 拖拽起手（真实 `mousePressEvent` / `mouseMoveEvent`）胶囊贴着光标、锚点作废；⑤ 卡片开着时 `_apply_position` 应用新 x/y，收起落在新位置 |

### 文档

| 文件 | 改动 |
|---|---|
| `docs/PR-REPORT-ISLAND-COLLAPSE-RETURNS-2026-11-06.md` | 本报告（新） |
| `docs/INDEX.md` | 「PR 报告存档」登记一行 |

### 未改动

- `_target_rect` / `_clamp_rect` 本身不动：展开时顶上去是对的（卡片要整块可见），只是收起不该留在那儿。
- 卡片高度没加上限（1182 px 的卡片在 1280 的屏上仍然顶到顶边、底下留 98 px），见第七节。
- `mouseMoveEvent` 的拖拽起手路径不动：它先 `collapse_card(animate=False)`（现在会落回锚点）再 `move(光标 − 抓取偏移)`，跟手语义由后者保证，测试 ④ 守住。

## 三、实现要点

- **记在哪、什么时候作废**：锚点只在 `expand_card`（normal → expanded）写入、`collapse_card` 读出即清空；中途 `_apply_position`（设置保存触发）覆盖它。没有别的读写点，所以不会影响拖拽、停靠、心跳夹屏（它们都读 `self.pos()`）。
- **为什么不改 `_target_rect`**：它在动画每帧收尾、`showEvent`、停靠切换等处都被调用，语义是「当前模式下、当前位置的目标矩形」；把「上一次展开前的位置」塞进去会让这些调用点在胶囊态也被拽回旧位置（比如用户刚拖完）。收起是唯一需要「回去」的时刻，所以只在 `collapse_card` 算一次目标。
- **`_finish_animations` 的顺序**：以前先清 `_geo_to` 再 `_set_free_geometry(_target_rect())`，对「终点 = 当前位置重算」的旧动画等价；现在收起的终点是别处，必须先跳到终点。实机动画路径（`_on_anim_tick`）本来就在 t≥1 时用插值后的位置重算，不需要改。
- **备选方案**：收起时按配置里的 x/y 回位——不行，配置只在拖拽松手时落盘，`_apply_position` 走的是另一条路，且会把心跳夹屏后的位置也抹掉。

## 四、性能分析

**方法（可复现）**：`python <scratchpad>/bench_collapse.py <tmp>`（离屏、假屏 1920×1040、卡片高 900、
`expand_card → _finish_animations → collapse_card → _finish_animations` 为一轮，预热 20 轮后计 300 轮；
两个新增操作各单独计时）。环境：Windows 11 Pro 26300，Python 3.13（`.venv`），PySide6 6.12，`QT_QPA_PLATFORM=offscreen`。

| 指标 | 实测 | 归属 |
|---|---|---|
| 展开 + 收起一轮（含两次 `_finish_animations`） | n=300，p50 0.615 ms，p95 0.845 ms，max 1.441 ms | 既有路径 + 新增 |
| `QPoint(self.pos())`（展开时记锚点） | 0.642 µs / 次（n=100000） | 新增，每次展开一次 |
| `_clamp_rect(QRect(anchor, _rest_size()))`（收起时算目标） | 13.57 µs / 次（n=10000） | 新增，每次收起一次；替代的是同量级的 `_target_rect()`（同样一次 `_rest_size` + 一次夹屏） |

**结论**：① 稳态开销无变化——胶囊态、停靠态、动画每帧都不读锚点；② 新增路径是每次展开 1 次 QPoint 拷贝、每次收起 1 次夹屏计算（替代原来那次 `_target_rect`），绝对成本十几微秒，触发频率 = 用户点开 / 收起卡片；③ 无新系统调用 / 网络 / 磁盘 / 线程；④ 内存多一个 `QPoint` 字段，收起即置 None。

## 五、实机运行记录

本机真实环境（三屏，主屏 3072×1280 逻辑 / DPR 1.25，任务栏在主屏底部）。

- **根因现场复现（修前，桌宠 pid 53352，main e6e4361c）**：枚举桌宠窗口发现岛在主屏顶边（物理 `(1859, 0, 673, 55)` = 逻辑 (1487, 0)）；日志里当天 5 次「灵动岛拖拽落点」（01:28 / 10:12 / 10:13 落在 y=1236，10:53 到 (2282,1018)，15:52:54 到 (2058,108)），之后无拖拽 / 隐藏 / 全屏记录。用探针点开胶囊：
  ```
  capsule 72814270 (1859, 0, 673, 55)
  after click rect (1303, 0, 673, 1478)      ← 卡片 1478 物理 = 1182 逻辑
  after second click rect (1303, 0, 673, 55) ← 收起留在顶边（且 x 还左移了 556 物理）
  ```
  再点一轮（DPI 无关进程、逻辑坐标，每 4 ms 记一次矩形）：展开 `(1042,0,538,44)→(1042,0,538,1182)`，收起回 `(1042,0,538,44)`——留在顶边，x 这轮没再动。
- **修后（桌宠从本分支重启，pid 57128，16:18:16 取得 overlay 锁，日志 0 条 WARNING / ERROR）**：配置里把岛放回用户常用的任务栏上方 (2045,1236)，探针点开再收起：
  ```
  start (2045, 1236, 484, 44)
  expand +169.8ms rect=(2045, 448, 484, 832)   ← 卡片放不下，被顶到 y=448
  collapse +183.4ms (2045, 1236, 484, 44)      ← 回到展开前的位置
  ```
  截图 `fix_island_back_above_taskbar.png`（scratchpad）：胶囊盖在任务栏正上方。第一次收起点击没生效——当时光标在副屏 (5057,575)，用户正在用鼠标，探针的点击被抢走；补一次就收起了，记录如上。
- **用户可见行为**：卡片开着时顶在屏幕能放下的位置，关掉回到原位；盖在任务栏上的岛不再「消失」到顶边。
- **边界 / 失败路径**：收起动画中段有一帧 `(2045, 760, 484, 44)` 的胶囊尺寸闪现（`_refresh → _update_size` 在动画中按当前位置重算尺寸），修前展开时同样有一帧 `(…,1182)` 直落——既有行为，不在本改动范围。
- **无法自动验证的部分**：展开期间 x 左移（用户那次 2058→1487、我那次 1487→1042）在离屏复现和真机独立岛（真实配置 + 消息记录，无会话历史）里都复现不出，岛代码里没有改 x 的路径（`_clamp_rect` 只在宽度超屏时动 x）；本修法不依赖它的机制（收起回锚点就把它吞掉），但原因未定，记在第七节。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet/dynamic_island.py tests/test_island_collapse_returns.py` | All checks passed |
| 聚焦（修前） | `pytest -q tests/test_island_collapse_returns.py` | 4 failed / 1 passed（主用例：收起落在 (1200,96)，不回 (1200,900)） |
| 聚焦（修后） | 同上 | 5 passed |
| 相关族 | `pytest -q tests/test_island*.py tests/test_dynamic_island*.py tests/test_multi_screen_interaction.py` | 343 passed |
| 相关族满载 3 遍 | 同上，与全量套件并行跑 3 遍 | 343 passed × 3（6.09 s / 6.27 s / 6.29 s） |
| 全量 | `python -m pytest -q`（隔离 worktree，`QT_QPA_PLATFORM=offscreen`，APPDATA 重定向） | 7 failed / 5980 passed / 14 skipped，9 min 13 s。7 个都是既有失败：6 个与 #23 / #24 报告同一组（image_directory_picker、festival_id_guard_survives_optimize、real_second_process_refused_on_overlay_topology、capture_window_rect_coordinates_and_clamping、host_icons_are_warmed_at_the_cards_size、modern_context_menu_has_compact_semantic_groups），第 7 个 `test_catalog_animation_count_guard_survives_optimize` 与 festival 那条同族（`python -O` 子进程返回 1），在 main 检出 e6e4361c 上单跑同样失败 |
| 架构红线 | `tests/test_architecture.py`（含在全量内） | 通过 |

## 七、已知限制与后续

- **卡片高度没有上限**：消息记录框开着 + 会话历史 10 行时卡片 1182 px，在 1280 的屏上仍顶到顶边、底下只剩 98 px；更矮的屏（1080）会直接截掉卡片底部。该按工作区高度限制可见行数或加滚动，另开 PR。
- **展开瞬间 x 左移一截**：实机见过两次（2058→1487、1487→1042，无拖拽记录），之后稳定在 1042——与「宽 2030 的矩形被夹到右边界」吻合，但岛代码里没有这样的矩形；离屏 / 独立岛复现不出。本修法收起即回锚点，用户看不到后果；根因待查。
- 动画中段的一帧尺寸闪现（第五节边界项）既有，不动。

## 八、风险与回滚

- 影响面：只有 `DynamicIsland` 的展开 / 收起 / 动画收尾；无配置键、无落盘格式变化。
- 回滚：`git revert` 即可，无残留状态；`_rest_anchor` 只在内存里。
