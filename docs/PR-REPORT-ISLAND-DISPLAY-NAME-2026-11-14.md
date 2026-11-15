# PR 报告：灵动岛名字可在设置里改（2026-11-14）

> **基线**：`6c15a540`（Settings: the model service list shows your edits… (#41)）
> **分支**：`claude/island-display-name-config-6cf145`　**日期**：`2026-11-14`
> **范围**：8 个文件（实现 6、测试 1、文档 1 + INDEX 登记）
> **关联**：[`SETTINGS-CHANGE-GATES.md`](SETTINGS-CHANGE-GATES.md)、[`PR-REPORT-TRAY-ICON-CUSTOM-2026-10-11.md`](PR-REPORT-TRAY-ICON-CUSTOM-2026-10-11.md)（`Config.reload()` 键白名单）

## 一、核心特性

用户问「灵动岛上的名字为什么是 shenshen、在哪改」。根因三层叠在一起：

1. 岛自己拼名字：`DynamicIsland._character_name` 写的是 `character_alias(id) or id`，跳过了
   `Config.character_display_name`（别名 → manifest `name` → id）。所以 Claude 角色在岛上显示成小写 `claude`，
   而右键菜单、聊天窗显示 `Claude`。
2. 内置 `shenshen` 角色包的 `videos/manifest.json` 只有 `body_box` / `head_box`，没有 `name`，
   就算走显示名也会落到 id `shenshen`。
3. 改名入口只有右键菜单「切换角色 → 重命名当前角色…」，设置页里没有；本机配置里 `character_aliases` 为 `{}`。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 岛名字和其他地方统一 | 岛改走 `Config.character_display_name`：用户起的名字 → manifest `name` → 角色 id |
| 2 | 设置页能改 | 「桌面组件 → 桌面胶囊（灵动岛）」里「显示名称」下面加一行「名字」（输入框，最长 24 字），留空 = 默认名（占位提示写着默认名） |
| 3 | 和菜单改名是同一个值 | 写 `character_aliases[当前角色]`，不另起「岛专用名」：菜单、聊天窗、主动识屏提示里的名字一起变 |

**红线 / 不变量**：

- 没动这一栏就保存，**不写** `character_aliases`——设置开着时用户从右键菜单改的名字不能被冲回旧值。
- 只改当前角色那一项，其他角色的别名原样保留。
- 右键菜单改名路径、`Config.set_character_alias` 的 24 字截断与「空名 = 恢复默认」语义不变。
- 没给 `shenshen` 包补默认 `name`：默认叫什么是用户的决定，这次只给入口。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/dynamic_island.py` | +13 / −1 | `_character_name` 改为「别名现取 → manifest 名按角色 id 缓存」。别名是内存字典读，每次现取，右键菜单改名不用等刷新；manifest 名要读盘 + 解析 JSON（实测约 0.46 ms），而这个方法每帧绘制都会被内容缓存键调用，所以按角色 id 记住，换角色时自动重取。 |
| `pet/settings_island_name.py`（新增） | +68 / −0 | 「名字」设置行：`island_name_row` 建输入框（初值 = 当前别名，占位 = `catalog.character_display_name`，`maxLength` 24，带 accessible name）；`save_island_name` 在保存时写回，只在值和打开时不同才写，只写当前角色那一项，不落盘（随对话框统一 `save`）。单独成模块是因为 `modern_settings_dialog.py` 有行数预算，先例是 `settings_island_icon.py`。 |
| `pet/modern_settings_dialog.py` | +5 / −1 | import 新模块；建行；插到「显示名称」行后面；`island_name_check.toggled` 接显隐；`_write_config` 写 `dynamic_island` 之前调 `save_island_name`（在 `config.reload()` 之后，吸收外部改动再写）。2259 → 2263 行，预算 2291 以内。 |
| `pet/settings_pet_controls.py` | +11 / −1 | 新增 `_update_island_name_controls`（依赖 `island_show_name`）；`dynamic_island_name_value` 进「启用灵动岛」的子项列表，岛关掉时一起隐藏；启用开关切换时同步一次名字行。 |
| `pet/locale/zh.json` / `pet/locale/en.json` | 各 +2 / −0 | `settings.island_name.title` / `settings.island_name.hint`。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_island_display_name.py`（新增） | +187 / −0 | 岛：没起名时回退 manifest 名（`claude` → `Claude`）、别名优先、manifest 每个角色只读一次且换角色重取、改名即时生效；设置页：行存在 + 初值 / 占位 / 最长 24、保存写当前角色（去首尾空格）且不碰其他角色、清空恢复默认、没动这一栏时不冲掉菜单改的名字、显隐跟「显示名称」和「启用灵动岛」。 |

### 未改动

- `assets/characters/shenshen/videos/manifest.json`：不替用户定默认名（见红线）。
- `pet/config.py`：`character_aliases` 早在 `reload()` 白名单里（`config.py` 第 1329 行附近），不用加键。
- `pet/sprite_menu_facade.py` / `pet/window.py` 的右键菜单改名：不动。改名写盘后，配置监视器
  （`AppShell._install_config_watcher`，进程内保存同样触发）走 `_apply_external_config_change → _sync_dynamic_island → refresh_from_config`，岛会重算宽度。

## 三、实现要点

- **为什么复用角色别名，而不是岛单独一个名字**：同一条鱼在岛上叫 A、在菜单和聊天里叫 B 更让人糊涂；
  `SETTINGS-CHANGE-GATES.md`「归属唯一」也要求同一个值只有一处归属。右键菜单的改名是命令入口，设置页这一行是偏好入口，写的是同一个键。
- **保存语义**：跟随「保存 / 保存并退出」（和同页其他岛设置一致），不做选图标那种「立刻写盘」——
  逐字输入时每个字都写盘、刷新岛没有意义。
- **为什么比较初值**：`_write_config` 先 `config.reload()` 吸收外部改动；如果无条件写回输入框的值，
  设置开着时从菜单改的名字会被打开时的旧值覆盖（`test_saving_without_touching_field_keeps_menu_rename`）。
- **缓存粒度**：只缓存 manifest 名，键是角色 id；别名不缓存。这样不依赖任何失效通知——
  就算 `settings_process_isolation` 关掉、配置监视器没装，菜单改名后的下一次重绘也是新名字。

## 四、性能分析

**方法（可复现）**：`.venv\Scripts\python.exe -I <scratchpad>\bench_name.py <仓库>`（脚本在本次会话 scratchpad，
逻辑：每种写法连调 20000 次取 5 轮最优的单次耗时；再给 `_character_name` 计数，强制冷 / 热各重绘一次）。
环境：Windows 11 10.0.26300、Python 3.13.15、PySide6 6.12.0、offscreen 平台；跑的时候后台有全量 pytest 在占 CPU，绝对值偏高，相对比例可信。

| 指标 | 实测 | 归属 |
|---|---|---|
| 旧写法 `alias or id` 单次 | 0.07 µs | 既有（热路径） |
| 不加缓存直接换成 `character_display_name` 单次 | shenshen 459.96 µs / claude 499.76 µs | 被否掉的方案 |
| 新 `_character_name`（缓存命中）单次 | 0.15 µs / 0.16 µs | 新（热路径） |
| 每次重绘调用 `_character_name` 次数 | 冷（内容缓存失效）2 次，热 1 次 | 既有 |
| 设置页保存多做的事 | 一次输入框取值 + 字典比较；值变了才多一次 `config.set`（无额外写盘） | 新（低频：用户点保存时） |

**结论**：

1. 稳态开销：每次重绘多约 0.08–0.16 µs（1–2 次调用 × 0.08 µs），相对一帧 16.7 ms 预算可以忽略到 1e-5 量级；
   不加缓存的替换会让每帧多约 0.46–0.5 ms 的读盘 + JSON 解析，所以加了缓存。
2. 新增路径：manifest 读取每个角色只发生一次（建岛或换角色后第一次取名），约 0.5 ms；设置页保存每次点保存一次，微秒级。
3. 没有新的线程、网络；磁盘读从「每次」变成「每个角色一次」；写盘次数不变（名字跟随原有的那次 `config.save()`）。
4. 内存：岛上多一个 `(角色id, 名字)` 二元组；设置页多一个 `QLineEdit`。

## 五、实机运行记录

**根因现场**（本机真实配置，只读）：

```text
> 读取 %APPDATA%\big-fat-fish\config.json
config.json shenshen {} True        # character / character_aliases / dynamic_island.show_name
> assets/characters/shenshen/videos/manifest.json
{ "body_box": [212, 60, 428, 330], "head_box": [185, 60, 436, 195] }   # 没有 name
```

**真实 Windows 平台跑设置页 + 灵动岛**（不是 offscreen；临时 `APPDATA`，没碰正在跑的桌宠和真实配置）：
`.venv\Scripts\python.exe -I <scratchpad>\live_check.py <仓库> <scratchpad>`，脚本建一个默认配置（角色 shenshen、岛开、显示名称开），
先截岛，再开 `ModernSettingsDialog` 翻到灵动岛那一页，在「名字」里输入「大肥鱼」，调 `_write_config()`，然后按配置重读刷新岛再截一次。真实输出：

```text
island before: 'shenshen' width 192
row visible: True text: '' placeholder: 'shenshen'
write_config: True
on disk alias: '大肥鱼'
island after: '大肥鱼' width 178
```

用户可见行为（人眼看了截图）：

- 设置页「桌面组件 → 桌面胶囊（灵动岛）」：「显示名称」下面多了一行「名字」，右侧是输入框，说明文字两行内显示完整，深色主题下边框和焦点框清楚。
- 灵动岛胶囊：前 `● shenshen 19:18 ⊂⊃`，后 `● 大肥鱼 19:18 ⊂⊃`，胶囊宽度跟着名字变（192 → 178 px）。

**没在真机做的**：没重启用户正在跑的桌宠走「设置独立进程保存 → 配置监视器 → 岛刷新」这一整条跨进程链路
（会打断用户正在用的桌宠与可能开着的设置窗）。这条链路本身没改：设置保存后岛刷新走的是既有的
`_apply_external_config_change → _sync_dynamic_island → refresh_from_config`，单元测试覆盖了 `_write_config` 写盘结果和岛按配置取名。
macOS / Linux 没有真机，只有共享代码路径（这次没有平台分支）。

**测试**：

- `tests/test_island_display_name.py`：改动前 5 个红（行不存在 / 岛显示 `claude`），改动后 8 个全绿。
- ruff：`All checks passed!`。
- 相关族（架构预算、设置页各测试、岛测试、i18n、`test_desktop_pet_features.py`）：339 过 2 失败，两个都在干净的 `6c15a540` 上原样失败、与本改动无关：
  `test_modern_context_menu_has_compact_semantic_groups`（菜单多了「列队」，期望表没更新）、`test_image_directory_picker_opens_right_drawer_with_three_column_masonry`（本机路径超 260 的基线）。
- 全量 `python -m pytest -q -p no:cacheprovider`（`QT_QPA_PLATFORM=offscreen`、临时 `APPDATA`）：**6179 passed、6 failed、14 skipped，618.62 s**。6 个失败全是本机既有基线、与本改动无关：上面两个，加 `test_festival_id_guard_survives_optimize`、`test_real_second_process_refused_on_overlay_topology`（子进程 cp1252 解码）、`test_capture_window_rect_coordinates_and_clamping`（多显示器负原点）、`test_session_card_metro.py::test_host_icons_are_warmed_at_the_cards_size`（main 上原样失败）。这一轮全量是在加 manifest 名缓存之前起跑的；缓存改动之后重跑了岛相关族（`test_island_display_name` / `test_island_content_cache` / `test_dynamic_island_revamp` / `test_island_english`，48 过）与 `test_pr_report_discipline`。
