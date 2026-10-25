# PR 报告：灵动岛「最近的对话」改成平铺卡片，每行带来源图标

> **基线**：`4a86da2`（feat(menu): VS Code 工作区目录按 WSL 发行版分行填）
> **分支**：`feature/claude-session-fish`　**日期**：`2026-10-14`
> **范围**：8 个文件（实现 4、测试 2、文档 2 含本报告）

## 一、核心特性

用户看了展开的灵动岛卡片后的反馈（2026-10-14）：「最近的对话」里有 VS Code 里开的、
PowerShell 里开的、WSL 终端里开的，前面要有对应的小图标方便一眼分辨；「最近的对话 (30)」
那一行看着还是普通文字，最好做成卡片；展开后的每一条也做成卡片；整体参考 Windows Phone
的 UI 风格，简洁清晰。

| # | 原来 | 现在 |
|---|---|---|
| 1 | 行首没有标记，靠小字「VS Code · WSL」分辨 | 行首一个 16 px 的单色图标：VS Code（两道尖括号）、本机终端（窗 + `>_`）、WSL 终端（一环三点）、脚本（自动化记号）；不知道来源的留空位，文字仍对齐 |
| 2 | 表头是透明底上的一行小字 | 表头是一块方角卡片，粗体，左对齐，悬停加亮 |
| 3 | 每行透明底，悬停才有一层灰 | 每行一块方角卡片，卡片之间 2 px 的缝；标题粗体 |
| 4 | 「进行中」只有右侧文字换色 | 另加左缘 3 px 主题色竖条 |
| 5 | — | 卡片底色随岛的配色：浅字（深底）用白色薄膜，深字（浅底）用黑色薄膜；没有圆角、描边、阴影 |

**红线 / 不变量**

- 行数据多一个 `host` 字段，其余字段与语义不变；没有 `host` 的行照常显示
  （`test_each_row_shows_an_icon_for_where_it_was_opened` 最后一条）。
- 表头文字格式不变（`最近的对话 (N) · 收起/展开`，状态行照旧顶替几秒）；点一行、右键
  菜单、折叠、滚动、省略规则全部不变（既有 15 条用例全过）。
- 一行占的高度从 36 变 40，卡片高度仍是 `行数 × ROW_HEIGHT`（岛侧按 `ROW_HEIGHT` 算，
  `test_island_passes_the_visible_row_cap_to_the_list` 仍通过）。
- 标题 / 路径仍按纯文本显示（外来内容不当富文本）。

## 二、修改文件说明

增删取自 `git diff 4a86da2 --numstat`。

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/island_history_panel.py` | +74 / −26 | 行拆成「外框（透明，只负责留缝）+ 卡片（`historyTile`）」；卡片里左侧 `icon` 标签，`set_data` 按 `host` 挑图标；`tile_colors(primary)` 按主文字色明暗给卡片底色；样式表改为方角卡片、`[live="true"]` 时左缘主题色竖条；表头粗体、方角、有底色；`ROW_HEIGHT` 36 → 40，表头 24 → 28 |
| `pet/claude_session_history.py` | +11 / −0 | `HistoryEntry.host`：`vscode` / `terminal` / `wsl` / `script` / 空（WSL 里的 VS Code 仍算 `vscode`） |
| `pet/app.py` | +1 / −1 | 给岛的行数据带上 `host` |
| `pet/context_menus/icons.py` | +11 / −0 | 新增 `vscode`、`terminal` 两个图标（`ubuntu` 上一轮已有；脚本用既有的 `automation`） |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_island_history_panel.py` | +68 / −0 | 4 条：四种来源各有图标且互不相同、没来源的留空位且文字对齐；表头与行真的画了底色、卡片之间有缝、表头粗体；进行中的行左缘像素是主题色；深底 / 浅底的卡片明暗相反 |
| `tests/test_island_session_history.py` | +16 / −0 | 1 条：`HistoryEntry.host` 的六种情况 |

### 文档

| 文件 | 改动 |
|---|---|
| `docs/PR-REPORT-ISLAND-HISTORY-TILES-2026-10-14.md` | 本报告 |
| `docs/INDEX.md` | 登记本报告 |

### 未改动

- `pet/dynamic_island.py`：岛只调用 `set_look` / `set_rows` / `set_session_history`，接口没变。
- `pet/session_history_service.py`：数据来源与动作没变。
- 卡片其余部分（余额、消息、三个按钮）没有动——这次只收到对列表的反馈；要是整张卡片
  都往这个风格靠，再单独做。

## 三、实现要点

**Windows Phone 风格取了什么。** 方角、无描边、无阴影、靠底色深浅与留白分层、粗体标题、
进行中用一道主题色竖条而不是圆点或徽章。没有取的：大面积纯色主题块（卡片是半透明底，
整块纯色会盖住岛的配色）、全大写标题（中文没有这回事）。

**卡片底色怎么定。** 岛有深 / 浅 / 玻璃三种配色，面板只拿到三个文字色。用主文字色的明度判断：
浅字说明底是深的，卡片用白色 7% 的薄膜；深字用黑色 5–6% 的薄膜。玻璃风格的文字是深色，
走后者。

**图标为什么单色、为什么 16 px。** 和菜单、设置页同一套描边图标，颜色跟岛的文字色走
（`vector_widget_icon` 的调色随控件主题）；行高只有 38，16 px 是能看清形状又不抢标题的尺寸。
「本机终端」没有区分 PowerShell 和 Windows Terminal——会话记录里只知道它是本机命令行。

**为什么行是「外框 + 卡片」两层。** 卡片之间的缝要透明（露出岛的底），而 QSS 的 `margin`
对 QFrame 背景不生效；外层透明、只留 2 px 下边距，内层画卡片，缝自然就有了。

## 四、性能分析

**方法**：一次性脚本，`QT_QPA_PLATFORM=offscreen`；面板 10 行，深色配色。

| 指标 | 实测 | 归属 |
|---|---|---|
| 一行 `set_data`（含画一个 16 px 图标、刷一次卡片样式） | 中位 174 µs，p95 255 µs（n=300） | 列表刷新时每行 1 次 |
| `_refill`（10 行全部重填） | 中位 2.5 ms，p95 3.7 ms（n=100） | 列表数据变化时 1 次 |
| `_restyle`（样式表重算） | 中位 4.1 ms，p95 4.8 ms（n=100） | 配色或宽度变化时 1 次（通常只在启动与改配置时） |
| 新测试 | 5 条约 0.6 s | — |

**结论**：没有稳态开销（列表刷新由既有的历史服务驱动，频率不变）；一次 10 行的刷新约
2.5 ms，其中每行约 0.17 ms 是图标与样式；没有新的系统调用、线程、磁盘、网络；没有常驻
对象。改样式前没有量过旧版的同一指标，这里给的是绝对值不是差值。

## 五、实机运行记录

```text
真实 Windows 平台渲染（不上屏），编造的 7 行（含 VS Code / 本机终端 / WSL 终端 / 脚本 / 两条进行中）：
浅色：表头卡片、7 块行卡片、图标各异、进行中的两行左缘蓝条、卡片之间有缝，无裁切
深色：同一布局，卡片是白色薄膜、文字浅色；两张都是 340×465（第一次截深色时岛的展开动画
      还没放完，卡片只有 155 高——截图脚本的问题，加了「先把动画收尾」之后正常）
```

真实桌宠在提交后重启，日志无报错；岛上的列表数据与原来相同，只是多了 `host`。

**没有验证的部分**

- 没有在真实桌面上展开过岛的卡片看效果（真实数据含用户工作信息，截图也不入库）；
  渲染用的是同一套控件和真实字体。
- 玻璃（glass）配色只按「深字 → 黑色薄膜」推断，没有渲染过。
- 高 DPI（1.25 以外的缩放）下图标与竖条的像素对齐没有看过。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests`、`git diff --check` | 通过 |
| 红 → 绿 | `pytest -q tests/test_island_history_panel.py tests/test_island_session_history.py` | 实现前 `5 failed, 46 passed`；实现后 `51 passed` |
| 聚焦 + 相关 | 全部 `test_island*` / `test_dynamic_island*`（15 个文件）+ `test_claude_session_history` `test_session_history_service` `test_architecture` `test_sprite_menu_parity` `test_vscode_workspaces` | 387 passed |
| 受影响时序族满载 3 遍 | — | 不适用：纯界面，没有线程或等待 |
| 全量 | `python -m pytest -q -p no:cacheprovider`（隔离 worktree，`4a86da2` 加本改动） | `5 failed, 5159 passed, 11 skipped in 511.41s`，5 个就是这台机器固定的环境性失败（路径超 260、两条子进程按 cp1252 打印中文、真实第二进程、多显示器负原点）。这次运行之后只改了本报告与索引登记 |

## 七、已知限制与后续

- 来源只分四类；PowerShell 与 Windows Terminal、cmd 不区分（记录里没有这个信息）。
- 卡片其余部分（余额、消息、按钮）还是原来的圆角风格，和列表不完全统一。
- 图标是简化记号，不是 VS Code / Ubuntu 的官方图形。

## 八、风险与回滚

- **影响面**：只有岛卡片里的「最近的对话」的外观；数据与动作不变。
- **配置 / 落盘**：无。
- **回滚**：`git revert` 后重启桌宠。

---

# 第二轮改进：来源图标用本机程序自己的图标

> **基线**：`fda37e7`（本报告第一轮的提交）　**日期**：`2026-10-14`
> **范围**：4 个文件（实现 2、测试 2）；报告与索引随本轮更新

## 九、第二轮：核心特性

用户问：VS Code、shell、WSL 能不能用本机装着的真图标？可以。Windows 外壳会把可执行文件
里嵌的图标交出来（`QFileIconProvider`，快捷启动菜单已经在用），所以：

| 来源 | 取谁的图标 | 本机实测 |
|---|---|---|
| VS Code | `Code.exe`（`code` 命令所在安装目录 → 用户目录安装 → 系统安装，依次找） | 找到，蓝色折带标志 |
| 本机终端 | PowerShell 7 的 `pwsh.exe`（`Program Files`），没有就系统自带的 `powershell.exe` | 7 没装，用了系统自带的；蓝色 `>_` 标志 |
| WSL 终端 | `System32\wsl.exe` | 企鹅 |
| 脚本 | 没有对应程序 | 手绘记号 |

程序不在、外壳取不到、非 Windows：退回第一轮的手绘记号，一行都不会空着。

**勘查里排除的**：`WindowsApps` 下的执行别名（`wt.exe`、`pwsh.exe` 那种）交出来的是通用的
程序图标，不是本尊，所以 Windows Terminal 没有进候选；Ubuntu 发行版用 `wsl --install`
装的没有带图标的应用包，注册表里只有 `Flavor: ubuntu`，所以 WSL 用的是 `wsl.exe` 的企鹅
而不是 Ubuntu 的圈。

## 十、第二轮：修改文件说明

增删取自 `git diff fda37e7 --numstat`。

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/host_icons.py`（新增） | +108 / −0 | `host_executable(kind)`：候选路径按顺序找；`host_icon(widget, kind, size)`：外壳取图 → 复用快捷启动的 `fitted_application_icon` 裁掉透明边并填满 → 失败退回手绘记号；按 (种类, 尺寸, 缩放) 缓存；`warm()` 预热；查找函数与取图函数都可注入 |
| `pet/island_history_panel.py` | +15 / −4 | `_set_icon` 改用 `host_icon`；面板建好 2.5 s 后预热一次（VS Code 的图标第一次要外壳解包 150 ms，别留给第一次展开卡片） |
| `tests/test_host_icons.py`（新增） | +138 / −0 | 8 条：装了就用程序的图标（注入的取图函数被问到正确路径、画出来的是它给的）；没装用手绘记号；外壳抛错也退回；同一种类同一尺寸只问一次；查找顺序（有 7 优先 7、没有就系统自带、非 Windows 为空）；预热取齐四种且之后不再问；面板按时安排预热；真机上四种都不为空、不抛 |
| `tests/test_island_history_panel.py` | +22 / −1 | 新增「行图标来自 `host_icon`」；「四种来源各不相同」那条改成不依赖本机装了什么（注入「一个都没装」） |

## 十一、第二轮：性能分析

真机，`QT_QPA_PLATFORM=windows`，每种各 1 次：

| 种类 | 第一次（外壳取图 + 裁剪） | 命中缓存 |
|---|---|---|
| VS Code | 150.1 ms | 44 µs |
| 本机终端（powershell.exe） | 11.4 ms | 48 µs |
| WSL（wsl.exe） | 6.3 ms | 41 µs |
| 脚本（手绘） | 0.2 ms | 15 µs |

**结论**：合计约 170 ms 的一次性开销，放在启动后 2.5 s 的单次定时器里（GUI 线程；
`QFileIconProvider` 走外壳 COM，没有放到别的线程）；之后每行取图标 40–50 µs。没有新的
磁盘写入、网络、常驻线程；缓存里 4 个小图标。启动期多这 170 ms 的 GUI 占用没有和别的
启动任务对比过时序，只知道它在 2.5 s 之后。

## 十二、第二轮：实机运行记录

```text
外壳取图探针（9 个候选）：Code.exe ✓ 真标志；code 命令所在处 ✓；wt.exe 别名 ✗ 通用图标；
pwsh 7 不存在；powershell.exe ✓；cmd.exe ✓（没用）；wsl.exe ✓ 企鹅；ubuntu 别名不存在
真实字体渲染（深 / 浅）：三种来源的行分别是 VS Code 标志、PowerShell 标志、企鹅；脚本是手绘记号
```

截图留在会话目录，没有入库。真实桌宠在提交后重启。

**没有验证的部分**：没有在真实桌面上展开过岛看；浅色岛上 PowerShell 图标的蓝底与白色薄膜
的对比只在渲染图里看过；高 DPI 下外壳给的是 20/40/60/320 四档，裁剪后 16 px 的清晰度没有
逐档比较。

## 十三、第二轮：测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests`、`git diff --check` | 通过 |
| 红 → 绿 | `pytest -q tests/test_host_icons.py tests/test_island_history_panel.py` | 新测试写在实现前但同一批应用，没有单独看红；接线后「四种来源各不相同」在真机上红了（三个真图标在 offscreen 下取出来一样）——改成注入「一个都没装」后绿，顺手把注入点改成调用时取默认值；最终 `282 passed`（含岛的全部家族） |
| 全量 | `python -m pytest -q -p no:cacheprovider`（隔离 worktree，`fda37e7` 加本轮改动） | `5 failed, 5170 passed, 11 skipped in 486.13s`，5 个就是这台机器固定的环境性失败。这次运行之后只改了本报告与索引登记 |

## 十四、第二轮：已知限制

- Windows Terminal 没有专门的图标（别名取不到本尊），本机终端一律显示 PowerShell。
- WSL 用的是 `wsl.exe` 的企鹅，不是具体发行版的图标。
- 「VS Code 工作区」菜单里的条目图标还是第一轮的手绘记号（Ubuntu 圈 / 四格窗），没有换成
  真图标——那边区分的是「WSL / 本机」，不是程序。要换也容易，`host_icon` 直接可用。
