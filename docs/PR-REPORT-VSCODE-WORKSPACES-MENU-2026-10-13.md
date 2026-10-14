# PR 报告：右键菜单「VS Code 工作区」；「音乐」从右键菜单下线

> **基线**：`cf973d4`（docs: 报告里引用的提交号改成历史改写之后的）
> **分支**：`feature/claude-session-fish`　**日期**：`2026-10-13`
> **范围**：19 个文件（实现 9、测试 8、文档 2 含本报告）

## 一、核心特性

用户的两条要求（2026-10-13）：

1. 主肥鱼右键菜单加一项「VS Code 工作区」：记住最近打开过的 VS Code 工作区和文件夹，点一条
   就切到那个窗口，没开着就打开；另外加一个设置，让用户指定工作区文件（`*.code-workspace`）
   所在的目录。
2. 右键菜单上的「音乐」不要了。追问后定的口径：**只摘菜单入口**，歌词气泡与唱歌联动保留，
   设置页「音乐关联」保留。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 菜单项「VS Code 工作区」 | 子菜单，放在原来「音乐」的位置（两套菜单都有）。开着的在前、带 ●，其余按最后活动时间倒序；WSL 里的带 `[WSL]`；同名的加父目录名或「工作区」后缀区分。最多 12 条（可设 3–30） |
| 2 | 三个来源 | 开着的窗口（VS Code 的窗口清单）；最近用过的（VS Code 给每个开过的文件夹 / 工作区留的状态目录，取最后修改时间，只看 60 天内）；用户目录里的 `*.code-workspace` |
| 3 | 点一条 | 开着的：找到它的窗口调到前台（和「跳到对话」同一套找窗口的办法）；没开或分不清是哪个窗口：`code [--remote wsl+发行版] <路径>`，VS Code 按路径去重 |
| 4 | 设置 | 「自动化与联动」页新增一节：工作区文件目录（本机目录或 `\\wsl.localhost\…` 形式的 WSL 目录）、菜单条数 |
| 5 | 「音乐」下线 | 新版模板、旧版建造器、注册表里都没有这一组；用户保存过的菜单布局里的这一组加载时清掉 |

**勘查结论（决定了方案）**：这个版本的 VS Code 不再在全局状态库里保存「最近打开」列表
（`history.recentlyOpenedPathsList` 这一项在用户机器上不存在，2026-10-13 实测）。能用的
只有窗口清单、每个工作区的状态目录的修改时间、以及用户自己的目录。

**红线 / 不变量**

- 全部只读：不写 VS Code 的任何文件；不常驻、不加定时器，条目在菜单弹出时现算。
- 没有 `vscode_workspace_entries` / `open_vscode_workspace` 这两个回调的宿主（旧 PetWindow）
  不出这一项（`test_the_main_fish_menu_lists_the_workspaces` 对两套模板都验；一致性测试把它
  登记为 overlay 独有项）。
- 开着的几个窗口之间保持 VS Code 清单里的顺序，不按名字重排。
- 同一个工作区在几个来源里都出现时只留一条
  （`test_open_ones_first_then_by_recency_and_each_workspace_once`）。
- 歌词功能的配置项原样还在（`test_the_lyric_feature_itself_is_untouched`）；设置页「音乐关联」
  没有动；`shared.py` 里的音乐菜单建造函数保留（没有调用方，留着是为了「最小影响」）。

## 二、修改文件说明

增删取自 `git diff cf973d4 --numstat`；新增文件给的是总行数。

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/vscode_workspaces.py`（新增） | +241 / −0 | 不碰 Qt。`normalize`（配置规整）；`parse_directory`（UNC 的 WSL 形式 → 发行版 + POSIX 路径）；`scan_workspace_dir`；`open_entries`（复用 `claude_session_jump.opened_workspaces`）；`recent_entries` / `_entry_from_storage`（遍历各编辑器的 `workspaceStorage/<id>/`，本机文件夹已删的不列）；`list_workspaces`（合并、去重、排序、截断）；`disambiguate`（同名加后缀）；`activate`（聚焦或 `code` 命令） |
| `pet/settings_vscode.py`（新增） | +48 / −0 | 设置页那一节：目录选择器（目录打不开时行下提示）+ 条数步进器；保存 |
| `pet/context_menus/shared.py` | +22 / −0 | `add_vscode_workspaces_menu`：两套菜单共用的建造器。没有条目时放一行禁用的提示 |
| `pet/context_menus/registry.py` | +5 / −53 | 登记 `vscode_workspaces`（标签、图标、`available = 宿主有 open_vscode_workspace`）；删掉 7 个 `music_*` 的导入、标签、图标、规格，以及只给它们用的 `_music_lyric_configured` / `_music_align_ready` |
| `pet/context_menus/legacy.py` | +4 / −15 | 原「音乐」子菜单的那段换成 `add_vscode_workspaces_menu(menu, pet, icons=False)` |
| `pet/menu_templates/modern-default-v1.json` | +1 / −10 | 删 `music` 子菜单节点，在 `size` 后面加 `vscode_workspaces` |
| `pet/sprite_menu_facade.py` | +49 / −36 | 新增 `vscode_workspace_entries` / `open_vscode_workspace`（后台线程里 `activate`，结果经 `_NoticeBridge` 的信号回 GUI 线程冒泡；桥挂在壳上长期存活）；删掉 `music_service_available`、`_is_music_group`、`_drop_music_group` 与那道「音乐服务门」。`_music_host` / `_music_lyric` / `install_music_lyric` 保留（歌词功能还用） |
| `pet/config.py` | +19 / −3 | 新顶层配置项 `vscode_workspaces`（默认值、`reload()` 白名单、加载时规整——惰性导入，避免和会话跳转模块成环）；`_MENU_LAYOUT_DROPPED_ACTIONS` 加 7 个 `music_*`；新增 `_MENU_LAYOUT_DROPPED_SUBMENUS = {"music"}`，`_drop_removed_menu_actions` 顺带清整组子菜单（否则老布局里留一个只剩分隔线的空壳） |
| `pet/modern_settings_dialog.py` | +3 / −0 | import 1 行、把那一节插进「自动化与联动」1 行、保存 1 行 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_vscode_workspaces.py`（新增） | +292 / −0 | 20 条：配置 2；目录解析与扫描 3；最近列表 2（真的状态目录结构，含两个编辑器、已删文件夹、过期、SSH 远程、坏 JSON）；合并 3（顺序与去重、同名区分、开着的从最近记录里学到发行版）；点一条 4（聚焦、同名分不清交给 `code`、没开的打开、失败有话说）；菜单 4（两套模板各一、空列表的提示、条数上限）；设置页 1（持久化 + 目录不存在的提示） |
| `tests/test_menu_music_entries_removed.py`（新增） | +137 / −0 | 4 条：模板与注册表没有这一组；两套菜单都不出「音乐」（歌词开关开着也不出）；老布局里的这一组加载时清掉、渲染时不留空壳；歌词配置项还在 |
| `tests/test_menu_layout.py` | +5 / −106 | 模板 id 快照、注册集合、根菜单顺序、渲染顺序里 `music` → `vscode_workspaces`；删掉「歌词对齐」子菜单的断言块和 `test_music_align_ready_and_callback_routing`（被测的辅助函数随菜单一起删了） |
| `tests/test_sprite_menu_parity.py` | +6 / −30 | `REQUIRED_LABELS` 去掉「音乐」、删 `MUSIC_LABELS` 与「音乐服务门」用例、`ALLOWED_EXTRAS` 加「VS Code 工作区」；音乐宿主用例只去掉对已删属性的那一行断言 |
| `tests/test_music_player_cache.py` | +4 / −6 | 冷缓存建菜单的用例：不再查找播放器条目；预热断言改为 `[]`（菜单里没有播放器条目了，预热只剩启动那一次） |
| `tests/test_desktop_pet_features.py` | +1 / −1 | 旧版菜单的标签快照：「音乐」→「VS Code 工作区」 |
| `tests/test_config_schema.py` | +1 / −0 | 白名单快照登记 `vscode_workspaces` |
| `tests/test_architecture.py` | +3 / −1 | `modern_settings_dialog.py` 行数预算 2403 → 2406（带日期说明） |

### 文档

| 文件 | 改动 |
|---|---|
| `docs/PR-REPORT-VSCODE-WORKSPACES-MENU-2026-10-13.md` | 本报告 |
| `docs/INDEX.md` | 登记本报告 |

### 未改动

- 音乐功能的模块（`music_*.py`、`now_playing.py`）、设置页「音乐关联」、歌词气泡、唱歌动画、
  对应的测试文件：按用户的口径一个没动。
- `pet/claude_session_jump.py`：只被复用（窗口清单、找窗口、聚焦、`code` 命令），没有改。
- `pet/window.py`（旧 PetWindow）：没有接新菜单项，按约定只修崩溃。
- `CONTEXT.md`：加一项菜单与一节设置都在既有模型内，没有改模型本身。

## 三、实现要点

**「最近用过」的来源为什么是状态目录的修改时间。** VS Code 给每个开过的文件夹 / 工作区在
`workspaceStorage/<id>/` 留一份 `workspace.json`（对应的地址）和 `state.vscdb`（这个窗口的
状态，活动时持续写）。没有别的地方记「最近」，这个修改时间是最接近「最后用过」的信号。
只看 60 天内的；本机文件夹已经不存在的不列（WSL 里的没法便宜地查，照列）。

**同名怎么区分。** 实机上三个不同父目录下的同名项目同时开着，还有一个同名的工作区文件。
名字撞上时，文件夹带父目录名（`core · Github-2`），工作区文件标「工作区」。只改显示的
名字，路径不动。

**点开着的那条为什么也可能走 `code` 命令。** 同名窗口有几个、标题分不出来时，不蒙最靠前
的那个（三选一有三分之二是错的），交给 `code --remote wsl+<发行版> <确切路径>`，VS Code
自己按路径去重、聚焦已开着的那个。这和「跳到对话」那次修复是同一个判断。

**后台线程 + 桥。** 找窗口、等它到前台、起 `code` 命令合计几百毫秒，不在 GUI 线程里做。
菜单的门面对象随菜单建了又丢，所以把结果信号的那个 `QObject` 挂在壳上长期存活，否则线程
结束时它可能已经没了。

**「音乐」只摘入口怎么做到最小。** 删的是：模板节点、旧版建造器里的那段、注册表里的 id、
门面里只为它存在的「服务门」。留的是：`shared.py` 里的建造函数（没有调用方）、歌词控制器
及其宿主面、设置页。老布局里的这一组靠既有的 `_MENU_LAYOUT_DROPPED_ACTIONS` 机制清掉，
另加一个子菜单级的集合——`music` 这个子菜单 id 不是 action，原机制清不到它的壳。

**没有采用的做法**

- 自己记一份「最近打开」：要监听窗口、要落盘、要处理删了的项目，而 VS Code 已经记了。
- 让菜单项在 GUI 线程里同步聚焦窗口：`focus_window` 会等到窗口真的到前台，最长几百毫秒。
- 把音乐整个删掉：用户明确要保留歌词和唱歌。

## 四、性能分析

**方法**：一次性脚本（会话内，未入库），在用户的真实机器上对真实数据计时。环境：
Windows 11 10.0.26300，Python 3.13.15，VS Code 开着 7 个窗口，`workspaceStorage` 下 56 个
目录，WSL 工作区目录里 7 个 `.code-workspace` 文件。

| 指标 | 实测 | 归属 |
|---|---|---|
| `list_workspaces()`（三个来源 + 合并，经 `\\wsl.localhost` 读 2 个工作区文件和扫 1 个目录） | 中位 30.3 ms，最大 33.6 ms（n=10） | 每次右键打开主肥鱼菜单 1 次，GUI 线程 |
| 其中：开着的窗口 | 23.1 ms（n=1） | 同上 |
| 其中：最近列表（56 个目录各读 1 个小 JSON + 2 次 stat） | 10.6 ms（n=1） | 同上 |
| 其中：扫目录（UNC，WSL 开着） | 14.7 ms（n=1） | 同上 |
| 点一条开着的（找窗口 + 聚焦） | 0.01 s（n=1；窗口本来就在前面那一层） | 用户点一次，后台线程 |
| 新菜单项多出的构建 | 没有单独量；12 个 `QAction` | 右键一次 |
| 设置页 | `modern_settings_dialog.py` 多 3 行；新一节两个控件 | 打开设置页时 |
| 新测试 | 20 + 4 条，合计约 1.2 s | — |

**结论**

1. **稳态开销**：没有。没有定时器、线程、缓存。
2. **新增路径**：右键打开主肥鱼菜单多约 30 ms（GUI 线程，读小文件）。WSL 没开着时经
   `\\wsl.localhost` 读文件会把发行版拉起来，那一次会慢几秒——没有量；只在用户配了 WSL 目录
   或开着 WSL 窗口时才会碰到。点一条：后台线程，GUI 不等。
3. **新的系统调用 / 网络 / 磁盘 / 线程**：每次右键读约 60 个小文件（全部只读）；点一条起
   1 个 daemon 线程，没开的工作区会起 1 个 `code` 进程。没有网络。
4. **内存**：没有常驻对象（桥是一个空的 `QObject`）。
5. **「音乐」下线**：菜单少了 8 个 `QAction`，少了一次播放器缓存的检查；没有量。

## 五、实机运行记录

全部在用户的真实机器上。工作区和项目的名字属于用户的工作信息，这里只记结构，不记名字；
截图留在会话目录，没有入库。

**勘查**

```text
全局状态库 state.vscdb：没有 history.recentlyOpenedPathsList；含 recent/history 的键只有终端历史等
storage.json：windowsState.openedWindows 8 条；profileAssociations.workspaces 36 条（无时间）
workspaceStorage：56 个目录，最新的 state.vscdb 改于 29 小时前（当时）
```

**真实数据上的列表**

```text
open: 7 (23.1 ms) | recent: 35 (10.6 ms) | scanned in the WSL workspace dir: 7 (14.7 ms)
recent kinds: wsl/multi 9, local/folder 5, wsl/folder 19, local/multi 2
menu would show: 12 | open first: 7 个 True 在前 | distros known for wsl entries: True
加同名区分之前的截图：某个项目名出现了三行一样的「<名字> [WSL]」、另一个两行一样的
加之后：unique labels 12 / 12 | 带后缀的 5（父目录名 4、「工作区」1）
```

**真的点了一条开着的**（本机的 BigFatFish 窗口，只聚焦）

```text
REAL activate: True | took 0.01 s
之后最前面的非桌宠窗口：code.exe，标题第一段 = BigFatFish | VS Code 窗口数 7 → 7
```

**设置页**：用真实的 Windows 平台渲染（不上屏）1100 px 与 720 px 两种宽度，「自动化与联动」
页里新一节在「Agent 联动」之后：目录选择器一行（提示折成两行）、条数一行；720 px 下没有
裁切，控件可达。第一版提示文案里有一段断不开的 UNC 示例，把页面撑宽、让既有的紧凑折叠
用例失败，已改成可换行的写法。

**没有验证的部分**

- **没有在真实桌面上右键点开过这个菜单。** 菜单是用真实数据在测试进程里建出来截的图；真实
  桌宠已重启、代码一致，但那一下没有人去点。
- **没有真的打开过一个没开着的工作区**（会在用户桌面上开一个新 VS Code 窗口），`code` 命令
  那条路只有用例。
- WSL 没开着时的首次读取耗时没有量。
- Cursor / Windsurf / VSCodium 的数据目录按同样结构读，本机没装。
- 「音乐」下线后歌词气泡与唱歌是否照常：没有在实机上放歌验证，只有「配置项还在、设置页
  没动、歌词模块的测试全过」。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests`、`git diff --check` | 通过 |
| 红 → 绿（音乐下线） | `pytest -q tests/test_menu_music_entries_removed.py` | 实现前 `3 failed, 1 passed`；实现后 `4 passed` |
| 红 → 绿（新功能） | `pytest -q tests/test_vscode_workspaces.py` | 纯逻辑模块先写好，接线前 `8 failed, 10 passed`（菜单、设置页、配置那几条红）；接线后全绿；同名区分那 1 条是先红后绿；最终 `20 passed` |
| 聚焦 + 相关 | 两个新文件 + 菜单三族 + 设置页七族 + `test_config_schema` `test_config_instance` `test_architecture` `test_music_player_cache` `test_update_entry_removed` `test_tray_icon_custom` `test_session_jump_workspaces` `test_session_pet_details` | 全部通过（最后一轮 157 passed；更早一轮 319 passed 含 1 个环境性失败） |
| 受影响时序族满载 3 遍 | — | 不适用：菜单用例对后台线程的结果用轮询等待（5 s 预算），没有固定 sleep |
| 全量，只含「音乐」下线 | `python -m pytest -q -p no:cacheprovider`（隔离 worktree） | `7 failed, 5118 passed, 11 skipped`：5 个是这台机器固定的环境性失败；另 2 个是本改动引入的——`test_music_player_cache` 在菜单里找播放器条目、`test_update_entry_removed` 的源码扫描被我改成多行的字面量绊到——都已修正（见上表） |
| 全量，最终代码 | 同上命令，另一个隔离 worktree | `5 failed, 5139 passed, 11 skipped in 552.30s`，5 个就是这台机器固定的那 5 个环境性失败（路径超 260、两条子进程按 cp1252 打印中文、真实第二进程、多显示器负原点）。这次运行之后只改了本报告里的一句措辞与索引登记；`tests/test_pr_report_discipline.py` 另外单独跑过 |

## 七、已知限制与后续

- 「最近用过」依赖 VS Code 的内部目录结构（2026-10-13 实测所见）；结构变了这一部分会读不到，
  菜单退化成只有开着的和目录里的。
- WSL 里已经删掉的文件夹仍可能出现在「最近」里（没法便宜地查它在不在）；点了会由 VS Code
  报错。
- 只认 `\\wsl.localhost\…` 和 `\\wsl$\…` 两种 WSL 目录写法。
- 菜单弹出时在 GUI 线程读约 60 个小文件（30 ms）；要是以后变慢，可以改成后台预算、菜单先出。
- `shared.py` 里留着 7 个没有调用方的音乐菜单建造函数；真要删音乐功能时一起清。

## 八、风险与回滚

- **影响面**：主肥鱼右键菜单多一项、少一组；设置页多一节；新配置项 `vscode_workspaces`。
- **配置 / 落盘**：用户保存过的菜单布局里的 `music` 子菜单会在加载时被清掉（不可逆，但它
  对应的功能已经不在菜单上）；`vscode_workspaces` 旧版本读到会忽略。
- **回滚**：`git revert` 后重启桌宠。被清掉的 `music` 布局节点不会回来，用户在菜单编辑器里
  重新加即可。

---

# 第二轮改进：系统图标与绿点；「显示本轮消费」下线

> **基线**：`da384c6`（本报告第一轮的提交）　**日期**：`2026-10-13`
> **范围**：12 个文件（实现 8、测试 4）；报告与索引随本轮更新

## 九、第二轮：核心特性

用户看了第一版菜单后的三条反馈：

1. 「开着的」那个圆点最好是绿色。
2. 区分 WSL 和本机，试试用 Ubuntu 图标和 Windows 图标。
3. 「自动化与联动」里的「消费统计」可以去掉了（用不到 DeepSeek）；有 Claude 的消费就换成
   Claude 的。

| # | 第一轮 | 第二轮 |
|---|---|---|
| 1 | 文字前缀「● 」 | 新版菜单：图标右下角一个绿点（`#30a46c`，与灵动岛「工作中」计数同色） |
| 2 | 文字后缀「[WSL]」 | 新版菜单：每条带图标——一环三点（Ubuntu，WSL 里的）或四格窗（Windows，本机的）。旧版菜单按约定无图标，仍用文字标记 |
| 3 | 设置页有「消费统计」一节，右键「桌宠控制」里有「显示本轮消费」 | 两处都下线。配置键 `agent_cost_enabled` 与结算代码保留（与「音乐」同一口径：只摘入口） |

**关于「换成 Claude 的」**：「显示本轮消费」靠 DeepSeek 的余额接口（开始、结束各查一次
余额相减）。Claude 没有余额接口，没法照搬。Claude 的用量已经在灵动岛的「今日用量」里
（读本机对话记录里的令牌数）。要做「每轮 Claude 用了多少令牌」的气泡是另一个功能，这里
没有做——设置页的那一节就空出来了，不放一个只读的状态项（设置门禁不准入「当前状态」）。

**图标的做法**：两个图标是和菜单里其他图标同一套描边语言手绘的简化记号，不是 Ubuntu /
Windows 的官方图形资产，不带品牌色。

## 十、第二轮：修改文件说明

增删取自 `git diff da384c6 --numstat`。

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/context_menus/icons.py` | +29 / −0 | `vector_menu_icon` 新增 `windows`、`ubuntu` 两个名字；新增 `badged_menu_icon`（在任一图标右下角画实心圆点）与 `OPEN_BADGE_COLOR` |
| `pet/context_menus/shared.py` | +11 / −2 | `add_vscode_workspaces_menu`：`icons=True` 时文字只留名字，图标按 WSL / 本机选、开着的加绿点；`icons=False`（旧版）保持文字标记。悬停提示在路径后标「（开着）」 |
| `pet/context_menus/registry.py` | +1 / −4 | 去掉 `agent_cost` 的导入、标签、图标、规格 |
| `pet/context_menus/legacy.py` | +0 / −2 | 去掉 `add_agent_cost` 的导入与调用 |
| `pet/menu_templates/modern-default-v1.json` | +0 / −1 | 去掉「桌宠控制」里的 `agent_cost` 节点 |
| `pet/config.py` | +2 / −0 | `_MENU_LAYOUT_DROPPED_ACTIONS` 加 `agent_cost`（老布局加载时清掉） |
| `pet/modern_settings_dialog.py` | +5 / −16 | 去掉「消费统计」一节、它的行、认领登记、保存回写；「Agent 联动」与「VS Code 工作区」各上移一位。文件从 2406 行降到 2395 行（预算 2406 不动，预算只是上限） |
| `pet/settings_pet_controls.py` | +0 / −2 | 不再建 `agent_cost_check` 开关 |
| `tests/test_agent_cost_entry_removed.py`（新增） | +71 / −0 | 3 条：两套菜单都没有「显示本轮消费」、同组其他项还在；设置页没有那一节与那个开关、保存不碰配置键；配置键照旧读进来、老布局里的那一项加载时清掉 |
| `tests/test_vscode_workspaces.py` | +44 / −4 | 菜单用例按模板分开断言（新版查图标与绿点像素、WSL 与本机图标不同；旧版查文字标记）；新增两个系统图标存在且不同、徽记版右下角是绿的 |
| `tests/test_menu_layout.py` | +0 / −2 | 注册集合与「桌宠控制」快照去掉 `agent_cost` / 「显示本轮消费」 |
| `tests/test_sprite_menu_parity.py` | +2 / −7 | `REQUIRED_LABELS`、新版能力清单、点击路由用例里去掉「显示本轮消费」 |

**未改动**：`pet/agent_cost.py`、`agent_link.py` 里的结算（仍读 `agent_cost_enabled`，老配置
里开着的照旧生效）、`shared.add_agent_cost` 建造函数（没有调用方）、`tests/test_agent_cost.py`
与 `test_agent_link.py`（全部通过）。

## 十一、第二轮：性能分析

**方法**：一次性脚本，`QT_QPA_PLATFORM=offscreen`，n=200 取中位数与 p95。

| 指标 | 实测 | 归属 |
|---|---|---|
| 画一个 `ubuntu` 图标 | 中位 46 µs，p95 101 µs | 每条 WSL 条目 1 次，右键时 |
| 画一个 `windows` 图标 | 中位 52 µs，p95 66 µs | 每条本机条目 1 次 |
| 带绿点的图标 | 中位 67 µs，p95 107 µs | 每条开着的条目 1 次 |
| 一次右键 12 条合计 | 按上面推算约 0.6–1.3 ms（没有单独量整组） | 右键时 |
| 设置页 | 少一节、少一个开关 | 打开设置页时 |

**结论**：没有稳态开销；右键打开菜单多约 1 ms 的绘制，在第一轮的 30 ms 读取之上。没有新的
系统调用、线程、磁盘或网络。内存没有变化（图标随菜单建了又丢）。

## 十二、第二轮：实机运行记录

```text
真实数据建出的新版子菜单：12 行，12 个图标；开着的 7 条右下角有绿点；
WSL 的 10 条是一环三点，本机的 2 条是四格窗；同名的带「· 父目录」或「· 工作区」后缀
设置页「自动化与联动」1100 px 与 720 px：第一节是「Agent 联动」，其后是「VS Code 工作区」，没有「消费统计」
```

截图留在会话目录，没有入库（含工作区名字）。真实桌宠在提交后重启，日志无报错。

**没有验证的部分**：同第一轮——没有在真实桌面上右键点开过这个菜单；没有真的打开过一个
没开着的工作区。另外没有在浅色主题下看过这两个图标（它们用菜单的前景色，与其他图标
一样随主题变）。

## 十三、第二轮：测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests`、`git diff --check` | 通过 |
| 红 → 绿 | `pytest -q tests/test_agent_cost_entry_removed.py tests/test_vscode_workspaces.py` | 实现前 `5 failed, 18 passed`；实现后新文件先剩 1 条红（我的断言用了只看顶层的查找函数，和产品无关），改断言后 `3 passed`，工作区文件 `22 passed` |
| 聚焦 + 相关 | 两个新文件 + 菜单三族 + `test_config_schema` `test_architecture` `test_agent_cost` `test_agent_link` | 436 passed（含 1 个环境性失败） |
| 全量 | `python -m pytest -q -p no:cacheprovider`（隔离 worktree，`da384c6` 加本轮改动） | `6 failed, 5144 passed, 11 skipped in 517.54s`：5 个是这台机器固定的环境性失败；第 6 个是本轮新测试文件当时的旧版本（断言用了只看顶层的查找函数），产品代码没有问题；该文件改断言后单独重跑 `3 passed`，之后没有再改任何产品代码，没有再跑一次全量 |

## 十四、第二轮：已知限制

- 「每轮 Claude 用了多少」没有做；要做的话数据源是本机的对话记录（`claude_usage_monitor`
  已经在读），呈现方式需要另定。
- 图标是简化记号；不想要品牌联想的话可以换成任意两个不同的几何记号，名字在
  `add_vscode_workspaces_menu` 里只出现一次。

---

# 第三轮修正：WSL 目录按发行版分行填

> **基线**：`9ab0740`（第二轮的提交）　**日期**：`2026-10-13`
> **范围**：4 个文件（实现 3、测试 1）；报告与索引随本轮更新

## 十五、第三轮：核心特性

用户在设置里填了 `/home/<me>/workspace`——WSL 里的原生写法，而第一版只认
`\wsl.localhost\<发行版>\…`，于是这个目录扫不出来、设置页提示「打不开」。用户接着提出：
这一节应该先列出本机有哪些发行版，目录填在对应发行版下面，更符合直觉。

| | 第一、二轮 | 第三轮 |
|---|---|---|
| 设置 | 一个「工作区文件目录」框，WSL 要写 UNC 形式 | 「本机目录」一行 + 每个已装的 WSL 发行版各一行（默认发行版排第一并标出，Docker 的内部发行版不列）+「菜单条数」 |
| 配置 | `{"workspace_dir", "menu_limit"}` | `{"workspace_dir": 本机目录, "wsl_dirs": {发行版: 发行版里的目录}, "menu_limit"}`。老值里的 WSL 路径（`/home/…` 按默认发行版，UNC 按它写的发行版）加载时搬到 `wsl_dirs` 下 |
| 菜单顺序 | 开着的 → 其余按最后用过的时间 | 开着的 → **用户目录里的** → 其余最近用过的。实机上 7 个开着的 + 35 个最近的、上限 12，原来的顺序会把用户特意配的目录整个挤出去 |

发行版列表来自注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Lxss`（每个子键的
`DistributionName`，`DefaultDistribution` 指向默认的那个），读一次 0.1 ms。设置页建一次读一次。

## 十六、第三轮：修改文件说明

增删取自 `git diff 9ab0740 --numstat`。

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/vscode_workspaces.py` | +139 / −14 | `normalize` 的新形状与老值迁移；`default_wsl_distro`、`wsl_distros` / `_registry_distros`（注册表）；`parse_directory` 认 `/` 开头的路径；`listing_path` / `directory_exists` / `scan_workspace_dir` 多一个 `distro` 参数（按发行版分行时发行版是明确的，不用猜）；`list_workspaces` 扫本机目录加每个发行版的目录，排序加「用户目录里的」这一档 |
| `pet/settings_vscode.py` | +50 / −20 | 行按发行版动态生成；每行自己的「目录打不开」提示；保存时本机没列出来的发行版（比如暂时卸了）的目录原样保留 |
| `pet/config.py` | +1 / −1 | 默认值加 `wsl_dirs: {}` |
| `tests/test_vscode_workspaces.py` | +121 / −8 | 配置 4（新形状、老值迁移、持久化、发行版列表）；扫描 2（`/` 开头的路径、按发行版分行、行里误填 UNC）；合并 2（每个目录都扫、用户目录不被挤出）；设置页 3（按发行版分行并持久化、没装的发行版保留目录、没有 WSL 只有本机一行）；注册表函数在真机上不抛 |

## 十七、第三轮：性能分析

| 指标 | 实测 | 归属 |
|---|---|---|
| 读注册表列发行版 | 0.09–0.14 ms（n=1 各） | 打开设置页 1 次 |
| 多扫一个发行版的目录 | 与第一轮相同（UNC 列目录约 15 ms） | 每次右键，每个配了目录的发行版 1 次 |

其余没有变化。

## 十八、第三轮：实机运行记录

```text
用户保存的旧值：{'workspace_dir': '/home/<me>/workspace', 'menu_limit': 12}
normalize 之后：  {'workspace_dir': '', 'wsl_dirs': {'Ubuntu-24.04': '/home/<me>/workspace'}, 'menu_limit': 12}
本机发行版（注册表）：['Ubuntu-24.04']（docker-desktop 被隐藏）
菜单（上限 12）：12 条，7 条开着的；用户目录里的 7 个工作区文件全部在列，位置 [1, 5, 7, 8, 9, 10, 11]
（1 和 5 那两个本来就开着，排在开着的那一档里）
设置页 1100 / 720 px：「本机目录」「Ubuntu-24.04（默认发行版）」「菜单条数」三行，720 px 下无裁切
```

**没有验证的部分**：多发行版的机器（本机只有一个可见的）只有用例覆盖；真实桌面上的
右键菜单仍没有人去点过。

## 十九、第三轮：测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests`、`git diff --check` | 通过 |
| 红 → 绿 | `pytest -q tests/test_vscode_workspaces.py` | 「认 `/` 开头的路径」那 4 条测试写在实现前，但和实现同一批应用，没有单独看红；按发行版分行那一批先把旧用例跑红（`2 failed`：配置形状变了）再改绿；「用户目录不被挤出」1 条先红后绿。最终 `30 passed` |
| 聚焦 + 相关 | 新文件 + 菜单两族 + 设置页三族 + `test_config_schema` `test_config_instance` `test_architecture` + 两个下线用例文件 | 168 passed |
| 全量 | `python -m pytest -q -p no:cacheprovider`（隔离 worktree，`9ab0740` 加本轮改动） | 最终代码：`5 failed, 5154 passed, 11 skipped in 460.62s`，5 个就是这台机器固定的环境性失败。（排序调整之前的那一版也跑过一次全量：`5 failed, 5153 passed`，同样只有这 5 个。）这次运行之后只改了本报告与索引登记 |
