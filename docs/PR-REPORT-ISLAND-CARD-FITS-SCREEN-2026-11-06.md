# PR 报告：灵动岛展开的卡片整块放进屏幕工作区（2026-11-06）

> **基线**：`91dcaac7`（Merge PR #25，灵动岛收起回原位）
> **分支**：`claude/silly-knuth-a6a8db`　**日期**：2026-11-06
> **范围**：6 个文件（实现 3、测试 1、文档 2）
> **关联**：`PR-REPORT-ISLAND-COLLAPSE-RETURNS-2026-11-06.md` 第七节「卡片高度没有上限」（本 PR 就是那条）；
> `PR-REPORT-ISLAND-OVER-TASKBAR-2026-11-05.md`（胶囊可以盖在任务栏上——本 PR 不改这条，只给**展开的卡片**另算边界）

## 一、核心特性

PR #25 修了「收起不回原位」，但没管卡片本身：「消息记录」6 行 × 58 + 「最近的对话」10 行 × 40
+ 标题 / 按钮，实机卡片 1182 逻辑像素，主屏 1280 高（工作区 1232）。展开时 `_clamp_rect` 把窗口
顶到屏幕能放下的位置，底下还要盖住任务栏；1080 高的屏（工作区 1032）直接截掉卡片底部，按钮
都看不见。修前离屏复现（真实面板 + 50 条消息 + 13 条历史，假屏）：

```
1366x768 work 720 : expanded rect=(900,0,340,950)   bottom=949  work.bottom=719   ← 顶到 y=0 还露不全
3072x1280 work 1232: expanded rect=(2045,330,340,950) bottom=1279 work.bottom=1231 ← 盖住任务栏
```

现在卡片（胶囊 44 + 内容）总高按**岛所在屏幕的工作区**算上限，放不下先压两个折叠框的可见行数；
展开态夹屏也按工作区（卡片是阅读面，不该盖任务栏）。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 高度上限 | 预算 = `availableGeometry().height()` − 上下各 16 − 胶囊 44。卡片不限行数时会多高（现高 + 两框被压掉的行）超出预算多少，就从行高总和更大的那个框一行一行拿，各自最少 2 行（`_CARD_FIT_MIN_ROWS`），多出的行在框里滚动 |
| 2 | 三处都重算 | `expand_card`、两框开合（`_on_message_toggled` / `_on_history_toggled` → `_refresh` → `_update_size`）、数据推送（`set_messages` / `set_session_history` 同样走 `_refresh`）、设置页改位置（`_apply_position` 挪完再算一次）；30 s 信息心跳也走 `_refresh`，换屏最迟一个心跳跟上 |
| 3 | 换屏即恢复 | 预算与配置的行数分开存（`set_row_budget` vs `set_max_visible`）：放得下的屏预算撤成 `None`，用户配置的 10 行原样回来 |
| 4 | 展开态不盖任务栏 | `_clamp_bounds`：expanded 按 `availableGeometry()`，其余模式仍按 `_placement_bounds`（整块物理屏，胶囊照旧可以盖在任务栏上） |
| 5 | 两框到底仍放不下 | 行数停在 2 行，`_clamp_rect` 兜底顶到工作区顶边（卡片本身比屏幕高只能这样） |

**红线 / 不变量**：停靠态（`dock_edge != none`）的展开 / 收回逻辑不动；PR #25 的 `_rest_anchor`
语义不动（收起回展开前的胶囊位置，本 PR 的真机记录与测试都复核了）；胶囊态夹屏仍按整块物理屏；
没有新配置键、无落盘格式变化；面板的 `set_max_visible` 语义不变。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/dynamic_island.py` | +48 / −2 | ① 常量 `_CARD_FIT_MIN_ROWS = 2`、`_CARD_SCREEN_MARGIN = 16`；② 新增 `_fit_card_to_screen()`：按工作区算预算，用 `ROW_HEIGHT` 整数算术决定两框各露几行后调 `set_row_budget`（预算不变时面板不重填），只看开着且有行的框；③ `expand_card` 在 `_sync_card_labels()` 之后、`_target_rect()` 之前调它；④ `_update_size` 在 expanded 态先调它（`_refresh` 的所有来路都经过这里）；⑤ 新增 `_clamp_bounds(screen)`：expanded → `availableGeometry()`，否则 `_placement_bounds`；`_clamp_rect` 与 `_clamp_to_screen` 都改用它；⑥ `_apply_position` 在 expanded 态挪到新位置后再 `_update_size()` + `_clamp_to_screen()`（新位置可能在别的屏上） |
| `pet/island_history_panel.py` | +27 / −2 | `SessionHistoryPanel`：类属性 `ROW_HEIGHT`；字段 `_row_budget`；`set_row_budget(rows \| None)`（变了才 `_refill`）、`row_cap()`（配置值与预算取小）、`visible_rows()`、`unbudgeted_rows()`；`_refill` 的滚动判定与 `body.setFixedHeight` 从 `_max_visible` 改成 `row_cap()` |
| `pet/island_message_panel.py` | +27 / −2 | `MessagePanel` 同上（两个面板是孪生类，接口一致） |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_island_card_fits_screen.py` | +178 / −0（新） | 假屏驱动真实展开 / 夹取 / 面板代码，面板里塞 50 条消息 + 13 条历史（不给定卡片高度）：① 1366×768（工作区 720）展开后底边 ≤ 工作区底边、顶不到 0、两框行数都在 [2, 配置值) 且多出的行滚动；② 折起消息框后「最近的对话」拿回行数、再展开回到同一分配；③ 换到竖屏行数恢复配置值、换回矮屏再压；④ 实机布局（3072×1280，岛盖在任务栏上 y=1236）展开不盖任务栏、收起回原位；⑤ 大屏露配置的行数；⑥ 1280×360 两框都停在 2 行、夹取兜底顶到顶边 |

修前跑：收集期 `ImportError`（`_CARD_FIT_MIN_ROWS` / `visible_rows` 不存在）；把断言换成现有接口的离屏
复现见第一节的两行输出（底边 949 > 719、顶到 y=0）。修后 6 passed。

### 文档

| 文件 | 改动 |
|---|---|
| `docs/PR-REPORT-ISLAND-CARD-FITS-SCREEN-2026-11-06.md` | 本报告（新） |
| `docs/INDEX.md` | 「PR 报告存档」登记一行 |

### 未改动

- `_placement_bounds` 不动：胶囊态 / 拖拽松手仍能盖在任务栏上（PR #23 的语义）。
- `_target_rect` 的停靠分支不动；`collapse_card` 不动（它在 `_mode` 改回 normal 之后才夹屏，所以按物理屏）。
- 面板的 `set_max_visible`（配置值）不动；`app.py` 推 `session_history_rows` 的路径不动。

## 三、实现要点

- **为什么是算术而不是逐步重排**：面板每改一次预算都要给全部行重填（`set_data` 50 行约 8.5 ms，见第四节）。
  行高固定（`body.setFixedHeight(行数 × ROW_HEIGHT)`，卡片布局随之线性长缩），所以「不限行数时的高度」
  = 现高 + Σ(被压掉的行 × ROW_HEIGHT)，超出多少直接算出各框该露几行，最后每框最多调一次 `set_row_budget`。
  预算没变时整个拟合就是一次 `sizeHint` + 几次整数运算（3.7 µs）。
- **先拿哪个框的行**：每次从「行高总和」更大的那个框拿一行（消息行 58、历史行 40），两框按像素大致均摊；
  到 2 行的框不再拿。两框都到 2 行还放不下就停，`_clamp_rect` 兜底。
- **预算与配置分开存**：`set_max_visible` 是用户要露几行（`agent_link.session_history_rows`），`set_row_budget`
  是这块屏放得下几行；取小。放得下的屏预算撤回 `None`，不然在矮屏上压过一次、换到高屏就留着矮屏的行数。
- **折着的框不算**：它不占高度，预算也不动它（省一次重填）；打开时 `toggled` → `_refresh` 会重算。
- **展开态按工作区夹**：高度上限按工作区算、夹取却按物理屏的话，岛盖在任务栏上展开时窗口底边会落到屏幕
  最底、卡片盖住任务栏——与「卡片整块可见」口径不一致。`_clamp_bounds` 按模式选边界，胶囊不受影响。
- **`_apply_position` 多算一次**：它开头的 `_update_size` 用的是旧位置所在的屏，挪到新屏后再算一次才对。

## 四、性能分析

**方法（可复现）**：`python -I <scratchpad>/bench_fit.py`（离屏、假屏、真实面板 50 条消息 + 13 条历史，
预热后计时；`QT_QPA_PLATFORM=offscreen`、APPDATA 重定向）。环境：Windows 11 Pro 26300、Python 3.13.15
（`.venv`）、PySide6 6.12.0。

| 指标 | 实测 | 归属 |
|---|---|---|
| `_fit_card_to_screen`，放得下、预算不变（3072×1280） | n=2000，p50 3.7 µs，p95 4.1 µs，max 12.7 µs | 新增，每次 `_refresh`（展开态）/ 每次展开一次 |
| `_refresh` 展开态一整次（含拟合） | n=300，p50 71.7 µs，p95 206 µs，max 815 µs | 既有路径 + 上一行 |
| 展开 + 收起一轮（1366×768，每次展开都要压行，但预算与上一轮相同） | n=300，p50 12.8 ms，p95 15.4 ms，max 20.6 ms | 既有路径（`_sync_card_labels` 两次 `retranslate` 重填 50+13 行是大头）+ 拟合 |
| 折起再打开消息框（两次重算、预算真的变了、两框各重填） | n=200，p50 4.3 ms，p95 6.3 ms，max 7.8 ms | 既有 `_refresh` ×2 + 新增重填 |
| `MessagePanel.set_row_budget` 单次变更（重填 50 行） | n=200，p50 8.5 ms，p95 10.2 ms，max 12.5 ms | 新增成本的上界：只在预算变了时发生 |

**结论**：① 稳态开销：胶囊态、停靠态、动画每帧都不走拟合；展开态每次 `_refresh` 多 ~4 µs。② 新增路径：
预算变化才触发面板重填（≤ 12.5 ms，50 行），触发时机 = 用户点开卡片 / 开合折叠框 / 换屏，每次最多两个面板
各一次；之后预算不变就不再重填。③ 无新系统调用 / 网络 / 磁盘 / 线程（`availableGeometry()` 本来就在
`_target_rect` 里读）。④ 内存：每个面板多一个 `int | None` 字段，无缓存。

## 五、实机运行记录

本机真实环境：三屏，主屏 3072×1280 逻辑（DPR 1.25），任务栏在主屏底部（工作区 1232），岛盖在任务栏上。

- **重启**：结束 pid 57440（姐妹会话从 `zen-dubinsky` 工作区起的），从本分支工作区起
  `BigFish.exe -m pet`，`pet-overlay-gate.log` 16:41:09 `acquired pid=19920`。
- **Win32 探针**（DPI 无关进程、`GetWindowRect` 逐 4 ms 记矩形，逻辑坐标；点胶囊左侧图标处）：
  ```
  capsule rect=(2009, 1236, 484, 44)   monitor=(0,0,3072,1280) work=(0,0,3072,1232)
  expand  +204ms rect=(2009, 166, 484, 1066)   bottom=1231 work.bottom=1231  top_ok=True bottom_ok=True
  collapse +181ms rect=(2009, 1236, 484, 44)   ← 回到展开前的位置（PR #25 语义不变）
  ```
  卡片整块在工作区内：顶在 y=166（不是 0），底边正好贴工作区底边、不盖任务栏。此刻卡片 1066 高
  （比上午的 1182 矮：消息记录条数变了），预算 1232 − 32 − 44 = 1156 放得下，所以**真机这一轮没有触发压行**——
  真机上三块屏最矮的工作区就是 1232，压行只能在离屏测试里证明（1366×768 → 消息 3 行 / 历史 6 行，
  1280×360 → 各 2 行）。要在真机看到压行得有 ≤ 1080 高的屏或更多内容，本机没有。
- **日志**：`pet-19920.log` 0 条 ERROR，2 条 WARNING 都是启动后 10 s 内的「tick 慢帧」（89.9 ms / 225.1 ms）——
  那几秒全量 pytest 正在后台把 CPU 打满；前三个进程（57128 / 62404 / 57440，起时没有测试在跑）同类 WARNING
  都是 0，本改动在卡片展开前也不执行任何代码。合并后从主检出重启的日志见第六节追记。
- **用户可见行为**：盖在任务栏上的岛点开，卡片从任务栏上沿往上展开、整块可见、不盖任务栏；再点收起回到任务栏上。
- **边界 / 失败路径**：展开动画中段仍有一帧 `(2009, 1236, 484, 1066)`（先按原位置直落满高再滑）——#25 报告记过的既有现象，不在本范围。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests/test_island_card_fits_screen.py` | All checks passed |
| 聚焦（修前） | `pytest -q tests/test_island_card_fits_screen.py` | 收集期 ImportError；现有接口下的离屏复现见第一节 |
| 聚焦（修后） | 同上 | 6 passed |
| 相关族 | `pytest -q tests/test_island*.py tests/test_dynamic_island*.py tests/test_multi_screen_interaction.py tests/test_settings_island_icon.py tests/test_work_briefing_links_and_island.py` | 375 passed |
| 全量 | `python -m pytest -q`（本工作区，`QT_QPA_PLATFORM=offscreen`，APPDATA 重定向，PowerShell 启动） | 6 failed / 5989 passed / 14 skipped，8 min 14 s。6 个全是既有基线失败（与 #23 / #24 / #25 报告同一组：image_directory_picker、modern_context_menu_has_compact_semantic_groups、festival_id_guard_survives_optimize、real_second_process_refused_on_overlay_topology、capture_window_rect_coordinates_and_clamping、host_icons_are_warmed_at_the_cards_size），无新增 |

### 追记：合并后从主检出重启（PR #26 squash `92727dde`）

16:51:37 `acquired pid=57172`（主检出 `C:\Users\limin\Github\BigFatFish`，main），此时没有测试在跑；`pet-57172.log` **0 条 WARNING / ERROR**——第五节那两条「tick 慢帧」确是全量 pytest 占满 CPU 所致。探针（同一手法）：

```
capsule rect=(2009, 1236, 482, 44)
expanded settled rect=(2009, 50, 482, 1182)   bottom=1231 work.bottom=1231  top_ok=True bottom_ok=True
collapsed rect=(2009, 1236, 482, 44)
```

这一轮卡片回到上午量到的 1182（消息记录条数又满了）：总高 1182 ≤ 1232 − 2 × 16 = 1200，仍放得下、不压行，整块落在 y=50..1231。完成标准（1280 高的屏上卡片整块可见、不顶到 y=0、收起回原位）在 main 上复核通过。

## 七、已知限制与后续

- 两框都压到 2 行仍放不下的屏（工作区高度不到约 480）只能顶到顶边、底部被截——卡片的固定部分（标题三行 + 按钮）
  没有再缩的余地；真要支持得让整块卡片滚动，另议。
- 预算只在 `_refresh` 的来路上重算；拖拽跨屏松手时卡片已收起（拖拽起手先收），下次展开再算，没有空档。
- 展开瞬间 x 左移的未解之谜（#25 报告第七节）本轮探针没有再现（x 一直 2009）。

## 八、风险与回滚

- 影响面：`DynamicIsland` 展开态的尺寸与夹屏边界、两个面板的可见行数上限；无配置键、无落盘格式变化。
- 回滚：`git revert` 即可；`_row_budget` 只在内存里。

---

## 第二轮：岛靠下时卡片开在胶囊上方，胶囊几乎不动（2026-11-07）

> **基线**：`5f597ee9`（main，含第一轮 #26 / #27）　**分支**：`claude/silly-knuth-a6a8db`
> **范围**：3 个文件（实现 1、测试 2）+ 本报告追记

### 一、核心特性（第二轮）

用户 2026-11-07 直接要求：「效率优先，不必做复杂。岛在屏幕底部点开确实会被顶到顶部，但过程一卡一卡；
岛靠近底部时让展开部分开在岛**上面**，岛本身就几乎不用动。」

第一轮之后岛在任务栏上点开：卡片往下长、整块窗口被夹到工作区里，胶囊从 y=1236 飞到 y=50，180 ms 内挪
1186 px；再加上展开瞬间 app 回推数据触发的那一帧整块闪现（第一轮第五节「边界」里记过的既有现象），就是
用户看到的「一卡一卡」。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 方向判定 | `expand_card` 比较两个方向各自夹屏后胶囊要挪多远（向下按工作区夹、向上按整块物理屏夹——胶囊本来就可以在任务栏上，卡片在它上面、整块在工作区里），挪得少的赢，相同取向下（`_prefers_card_above`） |
| 2 | 卡片在上 | 胶囊画在窗口底部那 44 px（`_capsule_top`，绘制 `painter.translate`），`_card_box` 放在上面（`resizeEvent`），按钮 / 磁贴命中与悬停倾斜都先经 `_capsule_point` 换到胶囊坐标；窗口尺寸变化时锚定胶囊底边（`_anchored_rect`），`_update_size` / `_target_rect` 都走它 |
| 3 | 收起动画不跳 | `_card_above` 到收起动画走完才失效（`_card_is_above` = 卡片开着或几何动画进行中），所以收起时胶囊一直钉在底部、卡片往下缩回去 |
| 4 | 动画中不闪现 | 几何动画进行中 `_update_size` 只改 `_geo_to`（按锚点重算、夹屏），不再 `setFixedSize` 直落终点——此前展开一发 `card_expanded`，app 回推数据 → `_refresh` → 整块卡片闪现一帧再从中途接着滑 |

**红线 / 不变量**：第一轮的行数预算（`_fit_card_to_screen`）、停靠态、`_rest_anchor`（收起回原位）都不动；
岛在屏幕上半部分时行为与第一轮完全一样（卡片在下、按工作区夹）；`_rest_size` 不变。

### 二、修改文件说明（第二轮）

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/dynamic_island.py` | +74 / −12 | ① 模块级 `_clamp_into(rect, bounds)`（`_clamp_rect` 与方向判定共用）；② 字段 `_card_above`；③ `_card_is_above` / `_capsule_top` / `_capsule_point`；④ `_button_hit`、`_metro_block_at`、`mouseMoveEvent` 悬停改用胶囊坐标；⑤ `resizeEvent` 按方向放 `_card_box`；⑥ `expand_card` 在拟合行数之后、算目标矩形之前调 `_prefers_card_above`；⑦ `_anchored_rect(size)`，`_update_size` 与 `_target_rect` 普通分支都用它；`_update_size` 在几何动画进行中只改 `_geo_to`；⑧ `_clamp_bounds`：expanded 且卡片在下 → 工作区，否则物理屏；⑨ `_paint_metro_capsule` / `_paint_capsule` 胶囊部分包在 `save / translate(0, _capsule_top) / restore` 里（卡片底板仍画整窗）；⑩ `_debug_state` 增 `card_above` |
| `tests/test_island_card_opens_upward.py` | +167 / −0（新） | ① 岛在任务栏上：卡片在上、胶囊底边不变、`_card_box` 在 y=0、`_capsule_top` = 高 − 44、收起回原位且 `card_above` 回 False；② 岛在顶部：仍向下、与第一轮一样；③ 两头都放不下时比位移（y=600 向上挪 256 < 向下 460 → 上；y=300 反过来 → 下）；④ 命中测试跟着胶囊到底部（铃铛在底部那 44 px 命中、顶部不命中；磁贴同理）；⑤ 开着时 `_refresh` 仍锚定胶囊底边；⑥ 展开动画进行中 `_refresh` 不直落整块、只改终点 |
| `tests/test_island_card_fits_screen.py` | +24 / −15 | 第一轮的「底边 ≤ 工作区、顶边 > 0」断言按新语义分叉：卡片在上时只要求顶边不出工作区、整块在物理屏内；「岛在任务栏上」用例改成断言胶囊留在任务栏上、卡片在上方 |

修前跑新测试：5 条红（`card_above` / `_capsule_top` 不存在；真机此前胶囊从 1236 飞到 50）。修后 6 passed。

### 三、性能分析（第二轮）

方法：`python -I <scratchpad>/bench_upward.py`（离屏假屏 3072×1280 / 工作区 1232，岛在任务栏上，消息 6 行 + 历史 10 行；
同环境）。

| 指标 | 实测 | 归属 |
|---|---|---|
| `_prefers_card_above`（两次 `_clamp_into` + 一次 `_rest_size`） | n=5000，p50 16.4 µs，p95 18.4 µs，max 355 µs | 新增，每次展开一次 |
| 展开 + 收起一轮（卡片在上） | n=300，p50 2.8 ms，p95 3.5 ms，max 4.3 ms | 既有路径（第一轮同口径 12.8 ms 是 50 条消息的重填；这里 6 条） |
| 绘制 | 多一对 `save / translate / restore` 与一次减法 | 每帧，纳秒级，不单独计 |

结论：① 稳态开销无变化（胶囊态不走任何新代码；`_capsule_top` 在卡片在下时恒为 0）；② 新增路径只在展开那一刻
多 16 µs；③ 动画中 `_update_size` 少了一次 `setFixedSize` + 一次直落 `setGeometry`，是省的；④ 无新系统调用 / 线程 /
磁盘；内存多一个 bool。

### 四、实机运行记录（第二轮）

同一台机器（主屏 3072×1280 / 工作区 1232，任务栏在底）。用户现在把岛放在屏幕中部 (2283, 603)，探针先用
`MoveWindow` 把岛挪到任务栏上 (2045, 1236)、测完挪回去（不经拖拽、不落盘），DPI 无关进程、逻辑坐标、逐 4 ms 记矩形。

- **修前（第一轮代码，pid 57172）**：岛在任务栏上点开 → `(2009, 50, 482, 1182)`，胶囊从 y=1236 飞到 y=50。
- **第二轮未含「动画中不闪现」时（pid 35720）**：
  ```
  moved to (2045, 1236, 397, 44)
    + 31.6ms rect=(2045, 715, 397, 565)   ← 整块闪现一帧（app 回推 → _refresh 直落）
    + 67.9ms rect=(2045, 975, 397, 305)   ← 再从中途接着滑
    +212.2ms rect=(2045, 715, 397, 565)
  expanded settled bottom=1279 capsule_bottom_before=1279  ← 胶囊底边没动
  collapsed rect=(2045, 1236, 397, 44)
  ```
- **最终代码（pid 42188，13:48:48 acquired）**：
  ```
  moved to (2045, 1236, 397, 44)
    + 57.6ms rect=(2045, 1057, 397, 223)   ← 从胶囊平滑长起，没有闪现帧
    + 98.2ms rect=(2045, 856, 397, 424)
    +206.7ms rect=(2045, 715, 397, 565)
  expanded settled rect=(2045, 715, 397, 565) bottom=1279 capsule_bottom_before=1279
  collapse: 565 → 440 → 332 → … → 44，+183.6ms rect=(2045, 1236, 397, 44)
  restored to (2283, 603, 397, 44)
  ```
  岛在中部 (2283, 603) 时点开仍是向下（565 高放得下）：`(2283, 603, 397, 565)`，胶囊同样不动。
- **日志**：pid 42188 一条 `tick 慢帧 54.2ms`（阈值 50），此刻两轮全量 pytest 在后台跑；pid 35720 一条语音端点握手 WARNING，与岛无关。
- **用户可见行为**：岛在哪点开，胶囊就留在哪；靠下时卡片往上长、靠上时往下长；不再有整块闪现。
- **没验证到的**：两头都放不下、按位移比大小的那条分支（本机 1232 的工作区放得下 565 的卡片），只有离屏测试 ③ 覆盖。

### 五、测试与验证（第二轮）

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests/test_island_card_fits_screen.py tests/test_island_card_opens_upward.py` | All checks passed |
| 聚焦（修前 / 修后） | `pytest -q tests/test_island_card_opens_upward.py` | 5 failed → 6 passed |
| 相关族 | 同第一轮的岛 / 多屏族 | 381 passed |
| 全量 | `python -m pytest -q`（本工作区，offscreen，APPDATA 重定向） | 6 failed / 6004 passed / 14 skipped，8 min 39 s（与两轮全量并行时的中间版本同样 6 失败 / 6003 通过）。6 个与第一轮完全相同的既有基线失败，无新增 |

### 六、已知限制（第二轮）

- 方向只在展开那一刻定；开着时拖拽会先收起，所以没有「开着换方向」的情形。
- 两头都放不下时仍要挪胶囊（挪得少的那边），这是卡片比半屏高的必然代价；第一轮的行数预算会先把卡片压矮。

### 七、第二轮补充：动画只动画面不动窗口；拖拽偏移按胶囊算（2026-11-07 下午）

用户试过第二轮后反馈：「向下展开时岛很稳定；向上展开时岛的位置不稳定，在原地上下轻微跳动，不顺滑。」

**根因**：几何动画逐帧 `setGeometry`，向上展开时顶边每帧上移 + 变高。层叠（半透明）窗口改位置 / 尺寸
后，DWM 先按**旧位图**在新位置合成一帧，等 Qt 重绘刷新才对——旧位图里胶囊画在旧高度的底部，整体
随顶边上提了一截，下一帧又回到正确位置，就是「上下轻微跳动」。向下展开顶边不动，旧位图原地不动，
所以稳。实机探针逐 4 ms 记矩形时窗口底边一直是 1279（几何本身没抖），抖的是画面，所以此前没抓到。

| # | 改动 | 说明 |
|---|---|---|
| 1 | 揭示式动画 | `_animate_to(target, reveal=True)`（展开 / 收起、非停靠态用）：窗口立刻摆到两头矩形的并集，180 ms 内只改 `_reveal_rect`（画面上露出的那块，全局坐标）和 `_card_box` 的遮罩（`_sync_reveal_mask`），窗口几何一帧都不改；到位后 `_clear_geo_anim` 撤遮罩、落到终点。停靠滑出 / 收回仍是真几何插值 |
| 2 | 画面按揭示矩形 | `_panel_rect()`：动画中 = 揭示矩形的纵向范围（横向整窗——胶囊内容按整窗宽排好，不随中途宽度变），否则整窗；卡片底板、`_capsule_top`、遮罩都按它 |
| 3 | 第一帧前就遮住 | `_animate_to` 里立刻 `_sync_reveal_mask()`，否则 `_card_box.show()` 到第一个 tick 之间整块卡片会先亮一帧 |
| 4 | 动画中 `_update_size` | 只改 `_geo_to`，并把窗口并集跟着扩（罕见：展开后 app 回推的数据把卡片撑高了） |
| 5 | 拖拽偏移 | 卡片在上方时窗口左上角是卡片顶；`_drag_offset` 此前按窗口左上角算，拖拽起手先收起再 `move(光标 − 偏移)`，胶囊往上跳一个卡片高（真机实测 1056 → 136）。现在按胶囊左上角算并夹进胶囊范围（按在卡片身体上起拖，收起后只剩胶囊，让它来到光标下） |

**文件**：`pet/dynamic_island.py` +64 / −17；`tests/test_island_card_opens_upward.py` +93 / −7（三条新用例：向上 / 向下
展开动画中窗口几何一帧不改、揭示矩形单调长、胶囊 `_capsule_top` 不变、遮罩动画完撤掉；从胶囊起拖胶囊贴着光标；
「动画中 `_refresh` 不闪现」改成断言揭示矩形不跳整块）；`tests/test_island_collapse_returns.py` +2 / −2（拖拽用例
改成按在胶囊上——它原来按的 (30,20) 在卡片在上时是卡片身体）。修前：3 条新用例红（窗口几何逐帧改）+ 拖拽用例红
（胶囊跳到 y=136）；修后相关族 430 passed。

**性能**：动画每帧少一次 `setGeometry`（原来逐帧移动 + 改尺寸 → 每帧一次 WM_WINDOWPOSCHANGED + 重建后备缓冲），
多一次 `QWidget.setMask`（一个矩形区域）；`_set_free_geometry` 的碰撞体回调从每帧一次变成动画首尾各一次。
收起动画期间卡片容器已 `hide()`，遮罩是空操作。`_prefers_card_above` 等不变。

**实机**（pid 40092，14:10:12 acquired，这次没有鼠标干扰；`MoveWindow` 到任务栏上测、测完挪回）：
```
moved to (2045, 1236, 397, 44)
  + 31.6ms rect=(2045, 715, 397, 565)     ← 窗口一次到位，之后 1.2 s 内几何零变化
expanded settled rect=(2045, 715, 397, 565) bottom=1279 capsule_bottom_before=1279
  +197.5ms rect=(2045, 1236, 397, 44)     ← 收起：动画期间窗口不动，到位一步变回胶囊
collapsed rect=(2045, 1236, 397, 44)
restored to (2448, 1021, 397, 44)
```
日志 0 条 WARNING / ERROR。上一轮（逐帧改几何的版本）同一探针是 11 帧中间矩形 (1057,223)→(715,565)。
前一次探针（pid 10128）被用户同时在用的鼠标叠成了三次拖拽（日志 14:06:11 / :13 / :29 三条「拖拽落点」），那次
的矩形轨迹不作证据；拖拽偏移 bug 就是在那次里暴露的。**顺滑与否最终以用户手感为准**——探针只能证明几何不再逐帧变。

**全量**：`python -m pytest -q`（本工作区，offscreen，APPDATA 重定向）6 failed / 6007 passed / 14 skipped，8 min 11 s；6 个与前两轮完全相同的既有基线失败，无新增。
