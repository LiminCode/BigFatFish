# PR 报告：配置全景（2/2）——后台采集，从右键菜单和岛的「模型连接」面板打开

> **基线**：`7d621e74`（PR #48，配置全景 1/2 合并后的 main）
> **分支**：`feature/config-panorama-entry`　**日期**：2026-11-15
> **范围**：19 个文件（实现 11、文字表 2、测试 6）+ 本报告与索引
> **关联**：[`PR-REPORT-CONFIG-PANORAMA-CORE-2026-11-15.md`](PR-REPORT-CONFIG-PANORAMA-CORE-2026-11-15.md)（1/2：采集、建图、渲染、命令行入口）

## 一、核心特性

上一步只有命令行入口。这一步把配置全景接进肥鱼：点一下，浏览器里几乎立刻出现这台机器上 AI 配置的地图，WSL 那一侧探完后页面自己更新。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 右键菜单「配置全景」 | 在「待办提醒」后面（tools 段）。两种渲染拓扑都有；不想要可以在菜单编辑里隐藏 |
| 2 | 岛的「模型连接」面板里的「配置全景」按钮 | 单独一行，点了面板收起 |
| 3 | 先出图、后补全 | 第一段只采 Windows 一侧（约 0.16 秒）就写页面、开浏览器；第二段去 WSL 里探测（约 6.7 秒）后重写。页面在等待期间每 3 秒自己重读文件 |
| 4 | 再次打开不出半张图 | 同一次运行里第二次打开时，WSL 那一侧先用上一轮的结果垫着，新的探完再换上 |
| 5 | 模型服务的线反映体检结论 | 「使用中的模型服务」通不通，取自岛上那个体检器的最近结论（命令行入口没有这个信息） |

**红线 / 不变量**：

- **不卡界面**。采集全在一条 daemon 线程里；GUI 线程只做三件事：拷一份配置、起线程、收信号后开浏览器。
- **线程不碰活的 `Config`**。配置在 GUI 线程上 `deepcopy` 一份交给线程。
- **不点就不跑**。没有定时器、没有启动时的工作、没有新设置项；服务对象第一次点的时候才创建。
- **只读、秘密不落盘、页面不联网**——同 1/2。
- **退出时不留尾巴**。`aboutToQuit` 把在跑的那一轮作废：它不再打开浏览器、不报完成。页面自己重读最多 40 次（两分钟），肥鱼中途退出也不会永远刷下去。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/panorama/service.py` | +165 / −0 | 新增 `PanoramaService`：`open()` 起一轮；线程里两段写盘，经 `_stage` 信号排队回 GUI 线程（`ConfigBackupSync` 同一个模式：`_generation` 作废过期结果、`_busy` 防重入、注入 `spawn` / 探针 / `open_page` 便于测试）。忙时再点只把现有页面再打开一次 |
| `pet/app.py` | +16 / −0 | `AppShell.open_config_panorama`（懒建一个服务）、`_panorama_health`（读体检器的 `state` / `detail`）；`_wire_window` 给旧窗口接 `on_open_config_panorama`；连接面板的 `panorama_requested` 连到同一个方法 |
| `pet/context_menus/registry.py` | +9 / −0 | 新动作 `config_panorama`：标签、图标（`branch`）、构建函数、可用性（宿主有 `on_open_config_panorama` 才显示） |
| `pet/menu_templates/modern-default-v1.json` | +1 / −0 | 默认布局 tools 段加这一项。用户已保存的布局由 `menu_layout._merge_future_default_actions` 自动并入，不需要迁移 |
| `pet/sprite_menu_facade.py` | +4 / −0 | overlay 拓扑的 `on_open_config_panorama`，走 `_hosts()` 找到 `AppShell.open_config_panorama` |
| `pet/island_connections_ui.py` | +11 / −1 | `ConnectionsWindow.panorama_btn` + `panorama_requested`。另起一行：英文下前两个按钮已经比磁贴宽，再并排会把面板撑宽 |
| `pet/island_connections.py` | +7 / −0 | `ConnectionsPanel.panorama_requested`；点了先收起面板再发信号（和「去设置修改」一致） |
| `pet/panorama/sources.py` | +2 / −1 | `facts["refreshing"]`（垫着上一轮结果、新的还在路上）也算 `meta.pending`，页面才会继续重读 |
| `pet/panorama/template.html` | +4 / −1 | 重读次数记在 `#` 后面，封顶 40 次 |
| `pet/panorama/claude_home_probe.py` | +1 / −1 | **修 #48 弄红的守卫**：`TOOL_DIRS` 里有一个目录名撞上了 `test_product_copy_has_no_external_brand_reference` 禁用的词，删掉 |
| `pet/locale/zh.json`、`en.json` | 各 +5 / −1 | 菜单两条、岛按钮两条（标签 + 悬停提示） |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_panorama_service.py` | +156 / −0 | 先写 Windows 半张 → 开浏览器 → 探 WSL → 重写，顺序钉死；第二次打开垫上一轮结果；忙时再点不重复采集；退出后结束的那一轮不开浏览器、不留垫底结果；WSL 探针抛异常时页面仍然结束等待；Windows 一侧失败时报失败并释放；线程看到的是配置的拷贝；真渲染落盘，最后一份 `pending` 为假 |
| `tests/test_panorama_entry.py` | +172 / −0 | 菜单项注册、只对接了回调的宿主显示、点击调到回调、英文标签无中文、默认布局里的位置；面板按钮发信号并收起面板、单独一行且不撑宽（中英文）；`AppShell` 从面板按钮和菜单走同一个方法、只建一个服务、体检结论来自体检器；没有岛时结论是 unknown |
| `tests/test_menu_layout.py` | +6 / −1 | 三处默认布局的 id 清单、一处渲染出来的菜单文字清单加上新项 |
| `tests/test_sprite_menu_parity.py` | +4 / −0 | 对照用的真窗口和桩 `AppShell` 都接上新回调（两种拓扑的菜单必须一致） |
| `tests/test_panorama_page.py` | +1 / −1 | 假 DOM 补 `location.hash` |
| `tests/panorama_samples.py` | +1 / −1 | 同上面那个守卫：样例里的目录名换掉 |

### 未改动

- `pet/context_menus/legacy.py`（旧版菜单模板是写死的、与上游保持一致）没有加这一项。
- 没有新设置项，`docs/SETTINGS-CHANGE-GATES.md` 不涉及。
- `tests/conftest.py` 没动：没有测试会遍历触发全部菜单项，真服务只在显式点击时才创建，测试里都替成了假的。

## 三、实现要点

- **为什么分两段**。实测 Windows 一侧 0.15 秒、WSL 一侧 6.5 秒（几乎全是 `claude mcp list` 逐个体检）。等全部采完再开浏览器，
  用户点完要干等 7 秒；分两段后 0.16 秒就有图。
- **为什么页面自己重读而不是起一个本地服务**。页面是 `file://` 上的一个文件，没法收到推送。让它在 `meta.pending` 为真时
  每 3 秒 `location.reload()`，肥鱼重写文件后下一次重读就是新的；`render.write` 先写临时文件再替换，浏览器读不到半个文件。
  代价是等待期间页面上的选中状态会丢；换来的是没有端口、没有监听线程、没有安全面。
- **垫底的结果只在内存里**。`_last_wsl` 不落盘：肥鱼重启后第一次打开，WSL 一侧显示「正在探测…」。
- **作废的那一轮**。`stop()`（或理论上的再次发起）让 `_generation` 前进；线程照常跑完并写文件，但它的信号被丢弃，
  也不把结果留作垫底——垫底的必须是一轮完整跑完的结果。
- **体检结论的时效**。取的是体检器「最近一次」的结论（通的时候它每 30 分钟查一次），不是点击那一刻现查。
- **菜单位置**。和「待办提醒」同级，在根菜单的 tools 段；没有放进「工具与帮助」子菜单，是为了一次右键就点得到。
  根菜单因此又长一项。

## 四、性能分析

**方法（可复现）**：在工作区里用真实 `%APPDATA%`、真探针、offscreen 的 `QApplication` 跑 3 轮 `PanoramaService.open()`，
`open_page` 换成记时间；同时挂一个 5 ms 的 `QTimer` 记相邻两次回调的间隔，作为 GUI 线程有没有被卡的度量。
环境：Windows 11 Pro 26300、Python 3.13.15、PySide6 6.12.0，WSL Ubuntu 24.04 已在运行。

```
service = PanoramaService(Config())          # 真探针
service._open_page = lambda path: 记下时刻     # 不真开浏览器
t0 = perf_counter(); service.open(); open_call = perf_counter() - t0
# QTimer(5 ms) 记间隔；finished 时停表。循环 3 轮
```

| 指标 | 实测 | 归属 |
|---|---|---|
| `open()` 在 GUI 线程上的耗时（拷配置 + 起线程） | 0.4 / 0.4 / 0.5 ms（n=3） | 新增，每次点击一次 |
| 点击到第一段页面写出（可以开浏览器） | 218 / 155 / 156 ms，中位 156 ms | 新增，线程里 |
| 点击到整轮结束 | 7288 / 6528 / 6897 ms，中位 6897 ms | 新增，线程里；其中约 6.5 秒是 `claude mcp list` |
| 整轮期间 GUI 线程的最大间隔（5 ms 定时器） | 7.0 / 6.8 / 7.5 ms；p99 6.3 ms | 说明界面线程没有被占 |
| 页面大小 | 62 950 字节，每轮写两次 | 新增 |
| 实机一次点击（见下节日志） | 第一段到 WSL 探完相隔 6.67 秒 | 与上面一致 |

**结论**：

1. **稳态开销**：零。不点就没有任何工作；没有定时器、监听或启动时的初始化。`pet.panorama.service` 只在第一次点击时 import。
2. **新增路径**：每次点击一轮。GUI 线程上 0.5 ms 以内；线程里 Windows 一侧约 0.16 秒，WSL 一侧约 6.7 秒。连点不会叠加：
   上一轮没完时再点只重新打开页面。
3. **新的系统调用 / 磁盘 / 网络 / 线程**：每轮 1 条 daemon 线程（跑完即结束）、6 个 git 子进程、1 个 `wsl.exe` 子进程（都带
   `CREATE_NO_WINDOW`）、写两次约 62 KB 的文件、调一次系统的「用默认浏览器打开」。肥鱼自己不发网络请求。
4. **内存**：常驻的只有服务对象和上一轮 WSL 结果（一个几十 KB 的字典）；采集过程的峰值不到 1 MiB（1/2 的报告里测过）。

## 五、实机运行记录

本机（Windows 11，三屏；WSL Ubuntu 24.04），2026-11-15。账号和 connector 名字从略。

- **从工作区重启桌宠**：`pet-overlay-gate.log` → `2026-11-15 01:21:02 acquired pid=45624`；`pet-45624.log` 里的资源路径在
  `.claude/worktrees/config-panorama` 下，启动到验证结束 0 条 WARNING / ERROR。
- **用户实机点击一次入口，浏览器正常打开**（用户确认）。同一时刻 `pet-45624.log`：

  ```
  2026-11-15 01:24:55,327 INFO 配置全景：Windows 一侧已写出，打开浏览器 …\big-fat-fish\panorama\panorama.html
  2026-11-15 01:25:02,000 INFO 配置全景：WSL 一侧探完，页面已更新（WSL 用了 6.67 秒）
  ```

- **落盘的页面**：`panorama.html` 62 978 字节，修改时间 01:25:01；里面 `"pending": false`；摘要
  「本机快照 2026-11-15 01:24:55 · 采集 Windows 0.24 秒 / WSL 6.67 秒 · 36 个站点 · 40 条路」。
- **体检结论接上了**：页面里「聊天 → 使用中的模型服务」这条线的状态是 `live`（1/2 的命令行入口下是 `unknown`）。
- **没能自动点击的原因**：计算机控制工具只能操作开始菜单里登记的应用，桌宠的窗口不在其中（截图里会被遮住、点击被拒）。
  改用脚本模拟鼠标点岛上的连接图标，两次都没点开面板；期间发现用户正在用鼠标（两次点击前光标位置不同），
  继续注入有点到别处的风险，于是停下，改由用户点击。**哪个入口点的没有记录**——日志只记了服务被调用，
  右键菜单和岛面板按钮各自有没有在真机上点过，这里说不准；两条路径由 `tests/test_panorama_entry.py` 覆盖。

**没做 / 没验证**：

- 岛面板里新按钮在真机上的样子（中英文、明暗主题）没有截图。
- 英文界面下的菜单项和页面只有测试覆盖。
- 肥鱼在采集途中退出的情况只有测试覆盖（作废那一轮、页面重读封顶）。

## 测试

- `ruff check pet tests`：通过。
- **红 → 绿**：撤掉产品改动后，`tests/test_panorama_entry.py` 8 个、`tests/test_menu_layout.py` 里与新菜单项有关的 2 个失败；
  恢复后全部通过。`tests/test_panorama_service.py` 是新模块的测试，没有「改之前」可言。
- **全量**（offscreen，PowerShell，9 分 42 秒）：**6309 passed，7 failed，14 skipped**。7 个都不是这次引入的：
  - 4 个本机环境基线：`test_image_directory_picker_…`、`test_festival_id_guard_survives_optimize`、
    `test_real_second_process_refused_on_overlay_topology`、`test_capture_window_rect_coordinates_and_clamping`；
  - `test_host_icons_are_warmed_at_the_cards_size`（已知）；
  - `test_modern_context_menu_has_compact_semantic_groups`、`test_compact_ai_provider_controls_stay_inside_their_setting_row`：
    在配置全景动工之前的提交 `c0f3471f` 上单独复跑，同样失败。
- **为什么这次跑了全量**：改动碰到应用入口、右键菜单、岛面板和文字表；更直接的原因是 1/2 只跑了相关测试，漏掉了一个扫全仓库的守卫
  （`test_product_copy_has_no_external_brand_reference`），把 main 弄红了。这个 PR 修掉了它，并用全量确认没有别的漏网的。
- 全量之后只加了两条 INFO 日志，重跑 `tests/test_panorama_service.py` + `tests/test_panorama_entry.py` → 16 passed。
