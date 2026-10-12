# PR 报告：开机自启改用 BigFish.exe、主页 README 改写、配图与原始素材入库

> **基线**：`cbaf378`（main：Merge pull request #1，`feature/claude-session-fish` 第一次合入）
> **分支**：`feature/claude-session-fish`　**日期**：`2026-10-11`
> **范围**：21 个文件，+295 / −10（`git diff --shortstat origin/main..HEAD`，不含本报告）：
> 实现 1 个、测试 1 个、文档 2 个、二进制图片 17 个（24.87 MB）。共 3 个提交。
> **关联**：上一份报告 [`PR-REPORT-CLAUDE-CODE-SESSION-FISH-2026-10-11.md`](PR-REPORT-CLAUDE-CODE-SESSION-FISH-2026-10-11.md)
> （BigFish 身份、洗牌式抽取、动图配图都在那一份里）；全量测试的潜伏崩溃背景见
> [`QT-LIFECYCLE-FULL-SUITE-STABILIZATION-2026-09.md`](QT-LIFECYCLE-FULL-SUITE-STABILIZATION-2026-09.md)。

## 一、核心特性

三件互不相关的事，各一个提交。

| # | 提交 | 能力 | 说明 |
|---|---|---|---|
| 1 | `72f243e` | 开机自启以 BigFish 启动 | 上一个 PR 让 `run.bat` 用 `BigFish.exe` 启动，但开机自启项仍写 `pythonw.exe`，所以开机自动起来的桌宠在任务管理器 / 任务栏里还是「Python」。现在自启命令优先用 `BigFish.exe`，已有的旧条目自动升级。 |
| 2 | `2032f2f` | 主页 README 改写 | README 开头原样是上游的介绍（标题、徽章、版本、下载都指上游）。换成本项目自己的说明：这是面向 Claude Code 的移植版、新增了什么、移除了什么、改进了什么、已知限制。上游原文整体保留在后面。 |
| 3 | `f22b490` | 配图与原始素材入库 | 用户手动收集的 13 张配图（`assets/big_blue_fat_fish/`）和 4 个原始素材（`raw-material/`）此前是未跟踪文件，现在入库，并在 `THIRD_PARTY_NOTICES.md` 新增第 6 节披露来源。 |

**红线 / 不变量**

- 打包运行（`sys.frozen`）的自启命令与升级条件不变。
- 没生成过 `BigFish.exe` 的检出，自启命令仍是 `pythonw.exe`，与改动前逐字相同。
- 自动升级只认**本检出自己**此前写下的那条 `pythonw.exe` 命令；别的检出、别的变体写的条目不动。
- macOS / Linux 的自启路径没有改动。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/autostart.py` | +36 / −9 | 新增 `_win_source_program()`：解释器旁边有 `BigFish.exe` 就返回它，否则退回原来的 `_pythonw_path()`。新增 `_win_source_command(program)`：把源码运行的命令模板收成一处。新增 `_win_command_needs_upgrade(command)`：打包运行沿用原判定（不是 `cmd /c start` 格式）；源码运行时，仅当已有命令与「本检出的 `pythonw.exe` 命令」逐字相同（忽略大小写）且现在算出来的命令不同，才算需要升级。`is_enabled()` 里原本只对打包运行做的升级改为调用它。`_win_command()` 的源码分支改走上述两个函数。模块说明同步。新增对 `app_identity.APP_NAME` 的导入（该模块零 Qt）。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_autostart.py` | +58 / −0 | 4 条：有启动器时命令用 `BigFish.exe`；没有时用 `pythonw.exe`；本检出的 `pythonw.exe` 旧条目在 `is_enabled()` 里被升级；别的检出的条目原样不动。用伪造的检出目录和既有的 `FakeWinreg`，不碰真实注册表。改动前第 1、3 条失败（2 failed, 6 passed），改动后全过。 |

### 文档

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `README.md` | +184 / −1 | 开头换成 BigFatFish 的说明（定位、快速开始、新增 / 移除 / 改进、已知限制、隐私与数据、与上游的关系）；原标题 `# dsh-pet-indesktop` 改为 `# 上游文档：dsh-pet-indesktop`，其后的上游原文一字未动。内容取自分叉点 `ee699c7` 以来 43 个提交的说明。 |
| `THIRD_PARTY_NOTICES.md` | +17 / −0 | 新增第 6 节：配图池与 `raw-material/` 里有从网络收集的图片，出处与授权没有逐张核实，版权归原作者，仅作个人非商业使用。 |

### 新增的二进制文件

| 位置 | 数量 | 大小 | 说明 |
|---|---|---|---|
| `assets/big_blue_fat_fish/` | 13 | 20.4 MB | 4 张 JPG、1 张 PNG、6 张 GIF、2 张 AVIF。配图池现在共 37 个文件、36.23 MB。 |
| `raw-material/` | 4 | 4.5 MB | 1 张 PNG、3 张 JPG。程序不读这个目录，只是存档。 |

两张 AVIF 程序读不了（实测 `QImageReader.canRead()` 为 `False`），而且配图清单按后缀过滤
（`speech_bubble_text.SELF_TALK_IMAGE_SUFFIXES`、`fun_image_popup` 的 `supported`，都不含 `.avif`），
所以它们不会被抽到，也只是存档。

### 未改动

- `run.bat`、`tools/make_launcher.py`：启动器的生成方式不变。
- `cleanup_stale_entries()`：按路径是否存在清理失效条目的逻辑不变。
- `tests/conftest.py`：没有动（见第六节的崩溃说明）。

## 三、实现要点

- **为什么放在 `is_enabled()` 里升级**：打包版的旧命令升级本来就在这里，菜单、设置页、启动时的
  自启自检都会调到它，不需要再加一个启动钩子，`pet/app.py` 不用动。
- **为什么只认逐字相同的旧命令**：自启注册表值按变体命名，源码运行的多个检出会共用同一个值名。
  如果「不等于当前命令就重写」，在检出 A 里打开一次设置页就会把检出 B 的自启抢过来。
- **程序名取 `sys.executable` 的同目录**：`run.bat` 启动的进程本身就是 `BigFish.exe`，此时
  `sys.executable` 已经是它；从 `python.exe` 运行（测试、命令行）时同目录下也能找到。
- **退路**：`BigFish.exe` 被删掉后，自启项指向不存在的文件；程序下次启动时
  `cleanup_stale_entries()` 会把它清掉，并由既有的「之前开启过但已被清理」气泡提醒用户。

## 四、性能分析

**方法（可复现）**：临时脚本，逐个函数循环计时；图片用 `QImageReader` 与 `pet.animated_image.open_movie`
逐个打开。环境：Windows 11 Pro 10.0.26300，Python 3.13.15，PySide6 6.12.0，`QT_QPA_PLATFORM=offscreen`，
真实注册表。

| 指标 | 实测 | 归属 |
|---|---|---|
| `_pythonw_path()`（改动前取程序名的方式） | 0.145 µs / 次（n=20000） | 既有 |
| `_win_source_program()`（新，含一次 `is_file`） | 13.31 µs / 次（n=20000） | 新增 |
| `_win_command()` 整条命令 | 87.26 µs / 次（n=20000） | 既有路径，含上一行新增的 13 µs |
| `is_enabled()`（真实注册表，条目已是新命令） | 102.2 µs / 次（n=5000） | 既有路径，现在每次多算一遍命令 |
| 新增 6 张 GIF 用 `open_movie` 打开 | 1.1 – 3.6 ms / 张 | 既有路径，新数据 |
| 新增 GIF 的帧数与一遍时长 | 13 – 122 帧；1.86 – 12.08 s | 既有路径，新数据 |
| 仓库体积 | +24.87 MB（17 个二进制文件） | 新增 |

**结论**

1. **稳态开销**：没有。自启相关函数只在打开菜单 / 设置页、启动自检、切换开关时被调用，不在任何
   定时器或绘制路径上。
2. **新增路径的成本与频率**：`is_enabled()` 每次约 0.1 ms。改动前它在源码运行时只读一次注册表；
   现在还要算一遍当前命令（约 87 µs，其中解析项目根目录是大头）来判断要不要升级。改动前的
   `is_enabled()` 耗时没有单独测。调用频率是「用户打开一次菜单或设置页」的量级。升级写注册表只发生一次。
3. **新的系统调用 / 网络 / 磁盘 / 线程**：每次 `is_enabled()` 多一次 `stat`（`BigFish.exe` 是否存在）
   和一次项目根目录的路径解析。没有网络，没有新线程。
4. **内存与缓存**：代码没有新增缓存。配图池多出 11 张可用图片（6 张动图），抽到动图时由既有的
   `QMovie` 逐帧解码（`CacheNone`），播完即释放；这条路径在上一个 PR 已经存在，这次只是数据变多。
   其中一张动图一遍 12.08 秒，略高于气泡的 12 秒上限，会在播完前收起。

没有测量的：新增动图播放时的内存峰值。最大的一张是 7.3 MB、122 帧、300×428。

## 五、实机运行记录

环境：用户本机，Windows 11，三块显示器，桌宠以 `BigFish.exe` 运行。

**前提的现场确认**（改动前读取的开机自启项，`Get-ItemProperty HKCU:\...\Run`）：

```text
dsh-pet-standalone = cmd /c start "" /D "C:\Users\limin\Github\BigFatFish" "C:\Users\limin\Github\BigFatFish\.venv\Scripts\pythonw.exe" -m pet --slot 0
```

**改动后**（同一命令读取）：

```text
cmd /c start "" /D "C:\Users\limin\Github\BigFatFish" "C:\Users\limin\Github\BigFatFish\.venv\Scripts\BigFish.exe" -m pet --slot 0
```

需要如实说明的一点：这次升级不是由手动命令触发的，而是跑测试时发生的——
`tests/test_settings_subslot_autostart.py` 会构造真实的设置对话框，对话框调用真实的
`autostart.is_enabled()`，于是把本机的旧条目升级了。结果正确，也说明升级路径在真实注册表上
走得通；但它同时说明**跑测试可能写真实注册表**（仅限「本检出的旧 `pythonw.exe` 条目」这一种情况，
升级后不再写）。打包版的同类升级此前就有这个性质。

**按自启项的命令实际执行一遍**（桌宠正在运行时）：

```text
> cmd.exe /d /s /c start "" /D "C:\Users\limin\Github\BigFatFish" "...\.venv\Scripts\BigFish.exe" -m pet --slot 0
pet-overlay-gate.log 新增一行：
2026-10-11 15:30:34 refused pid=7764 holder=33452 lock=...\overlay-instance.lock
```

命令能把程序拉起来，新进程被单实例闸门拒绝（已有 pid 33452 在运行），之后仍只有一个
`BigFish.exe`。这同时是一条「本该失败」的边界观察。

**失效条目判定**：对升级后的命令调用 `_win_command_target_exists()` 返回 `True`，
`cleanup_stale_entries()` 不会误删它。

**没有验证的**

- **真正的开机 / 登录自启**：没有重启或注销过。上面只证明了注册表里的命令正确、能拉起程序。
- **任务管理器里显示的名字**：这次没有截图确认。上一个 PR 已经确认过 `BigFish.exe` 进程在任务管理器 /
  任务栏里显示为 BigFish，这次启动的是同一个文件。
- **README 在 GitHub 上的渲染**：只在本地检查过 Markdown，页内链接的锚点没有在 GitHub 页面上点过。
- **新增的每一张配图在真实气泡里的显示**：只用程序自己的读图接口逐张打开过（见第四节），
  没有逐张在桌宠上看过。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests scripts tools` | All checks passed |
| 聚焦 | `pytest -q tests/test_autostart.py tests/test_settings_subslot_autostart.py tests/test_app_identity.py tests/test_architecture.py` | 28 passed |
| 读 README 的测试 | `pytest -q tests/test_requested_regressions.py tests/test_pr_report_discipline.py tests/test_tray_icon_ready.py "tests/test_desktop_pet_features.py::test_product_copy_has_no_external_brand_reference"` | 129 passed, 1 skipped |
| 受影响时序族满载 3 遍 | 不适用：新测试不涉及线程或事件循环 | — |
| 全量 | `python -m pytest -q -p no:cacheprovider`，跑了 3 遍 | 见下 |
| 架构红线 | `tests/test_architecture.py` | 通过（含在聚焦里） |

**全量的 3 遍结果**（都在自启改动之后、README 改动之前；README 是纯文档）：

| 遍 | 结果 |
|---|---|
| 1 | 原生崩溃，退出码 5。当时只保留了输出的末尾，崩溃位置没有记下来。 |
| 2 | 跑完：**4868 passed, 4 failed, 11 skipped**。4 个失败是本机既有的环境性失败：`test_image_directory_picker_opens_right_drawer_with_three_column_masonry`、`test_festival_id_guard_survives_optimize`、`test_real_second_process_refused_on_overlay_topology`、`test_capture_window_rect_coordinates_and_clamping`。 |
| 3 | 原生崩溃（`Windows fatal exception: access violation`），位置 `tests/test_proactive.py::TestUXFixesRound3::test_self_talk_yields_to_important_bubble` 的 `app.processEvents()`，约 64% 处。 |

**对崩溃的判断**：它与仓库文档记录的「Qt 生命周期崩溃点漂移」是同一类（旧版 `PetWindow` 显示后处理
事件时访问已释放的对象）。本 PR 的代码改动只有 `pet/autostart.py`，是注册表字符串逻辑，不在崩溃的
调用栈里。但**没有证实**与本 PR 无关：没有在相同条件下重测基线 `cbaf378`，所以不能排除本机
文件夹改名、新入库的配图（配图池变大会改变后台读图的时机）或别的因素让它更容易出现。
此前这个崩溃需要改动 `tests/conftest.py` 才会触发，现在不改也会间歇出现，这是一个变化。

## 七、已知限制与后续

- **全量测试间歇性原生崩溃**没有查原因。在查清之前，全量可能要重跑才能拿到一遍完整结果；
  重跑时要保留完整输出并加 `-X faulthandler`。
- `BigFish.exe` 被删除（例如重建虚拟环境时清空了 `Scripts`）而用户没有再运行 `run.bat`，下一次
  开机自启会失败一次；之后手动启动时失效条目被清理并提醒。
- 两张 AVIF 配图不可用。要用需要先转成 PNG / GIF，本 PR 没有做转换。
- 一张动图一遍 12.08 秒，超过气泡 12 秒的上限 0.08 秒。
- 打包版的自启命令没有变化，也不涉及 `BigFish.exe`。

## 第二轮：隐藏桌宠后灵动岛的两处改动（2026-10-11 追加）

> 这一轮在 PR 开出之后追加，对应一个提交。前面各节保持原样。

### 核心特性

| # | 能力 | 说明 |
|---|---|---|
| 1 | 修复：岛对话气泡里的「显示桌宠」没有把桌宠叫回来 | 用户实机报告：隐藏桌宠后点「显示桌宠」，按钮变了、桌宠没出现，之后按钮又变回「显示桌宠」。根因是 `AppShell._show_pets_from_island_chat` 只遍历 `instances[].win`，而 overlay 拓扑下它恒为 `None`——一只也没显示，却把岛写成了「已显示」；岛下次同步时又按真实状态改回去。与此前「岛卡片的聊天按钮没反应」（`9dca392`）是同一类。 |
| 2 | 改动：隐藏桌宠后单击灵动岛照常展开卡片 | 用户要求。此前隐藏时单击改弹岛对话气泡，卡片上的 Claude Code 会话与「最近的对话」就点不开了。现在单击一律展开卡片，恢复入口是卡片上的「显示桌宠」；隐藏时点卡片的「聊天」直接开完整聊天窗。 |

**没有删的**：`pet/island_chat.py` 与配置键 `dynamic_island.hidden_chat` 都还在。桌宠隐藏期间，
Agent 联动的提醒和 AI 回复到达时仍用这个气泡在岛上弹预览；更要紧的是，隐藏期间联动监视器
不暂停的条件（`_island_feedback_available`）挂在这个开关上，删掉它灵动岛上的 Claude Code 状态
在隐藏期间会停止更新。设置页的行名由「隐藏时对话气泡」改为「隐藏时在岛上提醒」，说明同步。

### 修改文件说明

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/app.py` | +22 / −33 | `_show_pets_from_island_chat`：overlay 拓扑下改调 `OverlayShell.set_pet_visible(True)`（它显示合成窗，并在显示之后自己同步岛状态），旧拓扑分支不变。macOS Dock 菜单的「显示桌宠」同样先走 overlay。`_open_chat_from_island`：桌宠隐藏时改开完整聊天窗。删除 `_chat_from_island`、`chat_requested` 的接线、`set_chat_available` 的调用。 |
| `pet/dynamic_island.py` | +4 / −25 | 单击分支去掉「隐藏 + `hidden_chat` 开 → 发 `chat_requested`」；随之删除 `chat_requested` 信号、`_hidden_chat_enabled`、`_chat_available` 与 `set_chat_available`（它们只服务于这条路由）。 |
| `pet/modern_settings_dialog.py` | +2 / −2 | `dynamic_island_hidden_chat` 这一行的名字与说明改成现在的含义。行数不变。 |
| `pet/config.py` | +1 / −1 | `hidden_chat` 默认值旁的注释同步。 |
| `README.md` | +1 / −0 | 「移除的功能」表加一行。 |
| `tests/test_island_shell_wiring.py` | +49 / −0 | 「显示桌宠」在 overlay 拓扑下必须交给壳、且不许抢先把岛写成已显示；隐藏时卡片的「聊天」开完整聊天窗。 |
| `tests/test_overlay_chat_proactive.py` | +30 / −0 | 用真实 `OverlayShell` 走「隐藏 → 气泡里的显示桌宠」，断言合成窗重新可见、岛状态先 `False` 后 `True`。 |
| `tests/test_island_chat.py` | +37 / −52 | 隐藏时单击展开卡片、卡片按钮是「显示桌宠」且能发出切换请求；删掉两条测 `_chat_from_island` 的用例，换成「AppShell 不再有这条入口」。 |
| `tests/test_dynamic_island_revamp.py` | +8 / −29 | 两条按构建分支的用例合成一条：隐藏时单击在所有构建都展开卡片。 |

去掉产品改动（`git stash` 掉 `pet/app.py`）重跑：新增的两条「显示桌宠」用例都失败；恢复后通过。

**故意没动**：`PetInstance.open_quick_chat` 里「隐藏时改弹岛气泡」的分支只在旧拓扑（`PetWindow`）下
可达，按 `AGENTS.md` 对该面「只修崩溃」的约定没有改。

### 性能分析

**方法**：临时脚本，真实 `DynamicIsland` / `IslandChatBubble`，`QT_QPA_PLATFORM=offscreen`，同上环境。

| 指标 | 实测 | 归属 |
|---|---|---|
| 隐藏时单击 → 展开卡片（`expand_card` + 动画收尾） | 中位 0.577 ms，最大 1.754 ms（n=200） | 既有路径，现在隐藏时也走它 |
| 改动前：首次构造岛对话气泡 | 5.49 ms（1 次） | 不再由单击触发 |
| 改动前：弹出已构造的气泡 | 中位 0.054 ms，最大 0.942 ms（n=200） | 不再由单击触发 |

**结论**：① 稳态开销无变化，没有新增定时器；② 隐藏时每次单击多约 0.5 ms（展开卡片比弹出一个
已建好的气泡贵），触发频率是用户点击；展开卡片会触发既有的卡片刷新（会话汇总、最近的对话的
后台回填，一分钟内不重复）；③ 没有新的系统调用、网络、磁盘或线程；④ 内存：单击不再构造
对话气泡，只有隐藏期间真的来了提醒才会构造。

### 实机运行记录

- **根因的现场确认**：用户本机配置 `dynamic_island.click_action = "expand"`、`hidden_chat = true`
  （读自 `%APPDATA%\dsh-pet-standalone\config.json`），即隐藏后单击走的正是对话气泡这条路由；
  桌宠以 overlay 拓扑运行（`pet-overlay-gate.log` 有 `acquired` 记录）。
- **修复后**：桌宠已重启到新代码（`2026-10-11 17:50:07 acquired pid=4916`）。
- **没有验证的**：没有在真实桌面上用鼠标走一遍「隐藏 → 点岛 → 显示桌宠」。自动化点击会抢走用户
  正在使用的鼠标，这一步交给用户确认。macOS Dock 菜单的改动没有 Mac 可测。

### 测试与验证

| 门 | 结果 |
|---|---|
| ruff（`pet tests scripts tools`） | All checks passed |
| 聚焦（岛 / 岛对话 / 岛接线） | 71 passed |
| 全量（`-X faulthandler`，完整输出保留） | **4871 passed, 4 failed, 11 skipped**，没有崩溃；4 个失败是本机既有的环境性失败 |

到此全量一共跑了 4 遍完整的：2 遍跑完、2 遍原生崩溃（见第六节）。

## 八、风险与回滚

- **第二轮**：`hidden_chat` 键与默认值不变，没有配置迁移；回滚后隐藏时单击恢复为弹对话气泡。
- **影响面**：仅 Windows、仅源码运行的开机自启命令。没有新增配置键，没有配置迁移。
- **落盘状态**：升级会改写 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 下本变体的值。
  `git revert` 之后这个值**不会自动改回** `pythonw.exe`；它仍然有效（`BigFish.exe` 还在），
  想改回去在设置里把开机自启关掉再打开即可。
- **图片**：入库的是从网络收集的图片，授权没有逐张核实；仓库是公开的。`git revert` 可以把它们从
  工作区移走，但已经推送的历史里仍然有。
- **README**：纯文档，回滚无残留。
