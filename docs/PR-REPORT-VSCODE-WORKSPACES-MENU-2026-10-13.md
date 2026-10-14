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
