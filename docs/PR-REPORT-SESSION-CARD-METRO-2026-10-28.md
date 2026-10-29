# PR 报告：会话小鱼详情卡改成 Metro 风格，加上下文用量、VS Code 工作区和来源程序图标

> **基线**：`11ebdd6e`
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-28
> **提交**：`81d67cf8`、`1072039a`、`61950be1`、`20a8e069`、`930527da`、`9c04ba36`、`331bc658`、`03983cb4`
> **范围**：实现 14 个文件（含文案 2 个）+ 测试 1 个（新）/ 7 个（改）
> **过程**：五轮，每轮用户看实机卡片后提意见；下表是最终状态

## 一、核心特性

点会话小鱼弹出的详情卡。原来是圆角卡片，标题加粗之后全是同一号字：
- 「工作中 · Opus 5.5 · high · 已 3 分钟」挤在一行；
- 「VS Code 插件 · 路径 · 分支」挤在另一行；
- 长问题、长路径在实机上会被截掉一截。

| # | 内容 | 原来 | 现在 |
|---|---|---|---|
| 1 | 外观 | 圆角、阴影 | **Windows Phone / Metro**：方角、平铺、无阴影 |
| 2 | 在哪打开的 | 一行灰字里的「VS Code 插件」，桌面版会话显示原始的 `claude-desktop` | 页头左边一块白色小方磁贴，放**那个程序自己的图标**（Claude 桌面版 / VS Code / PowerShell / wsl.exe 的企鹅），旁边写「Claude 桌面版」「VS Code 插件」「终端 · WSL」 |
| 3 | 标题 | 加粗、自己折行 | 页头强调色带子上，大而轻（雅黑 UI 细体），最多 2 行 |
| 4 | 状态 | 一行文字 | 强调色小磁贴按阶段画记号（工作中三个点、等批准感叹号、等回复对勾、休息月亮）+ 阶段名 |
| 5 | 模型 / effort / 时长 | 混在状态那行 | 状态下面一行**灰色小字 + 小图标**（用户说这些不重要），名称在悬停提示和无障碍名字里 |
| 6 | 上下文 | 没有 | 「上下文　446k / 1M · 45%」加一根方头平条；认不出窗口大小的模型只写用量 |
| 7 | 最近的问题 | QLabel 自己折行，长了在实机上只露两行半 | 按宽度折好行，最多 4 行、末尾省略，悬停看全文 |
| 8 | 工作区 / 目录 / 分支 | 一行灰字 | 带图标的几行。VS Code 会话多一行工作区（多文件夹的注明几个文件夹）。**目录和分支放在同一块磁贴里**，用**等宽字**（Ubuntu Mono，没装用 Consolas）。放不下不省略，**左右滑**：滚轮上下滚也当左右滑，底下有一根细滚动条；一换内容先停在最右端，用户滑过就不再拽回。字可以拖选；每行右边一个**复制按钮**，复制整个值后提示「路径已复制」「分支名已复制」。**光标移到（或点）行首的目录 / 分支图标**，就贴着它弹出整个值，不用拖滚动条 |
| 9 | 按钮 | 三个圆角描边按钮，英文时字被截（「Jump to cha」） | 强调色的「跳到对话」占满剩下宽度；打开文件夹（文件夹图标）、复制恢复命令（终端图标，免得和行内的复制按钮混）是方形图标按钮，有悬停提示和无障碍名字，都会朝光标倾斜，有键盘焦点描边 |
| 11 | 悬停提示 | 系统默认的小字 | 卡片样式表给提示定字号（不小于正文）和配色；卡片不在前台也弹；省略了的工作区名、状态，光标一移上去就显示全文 |
| 10 | 文字大小 | 跟气泡文字大小走，再乘 1.25（用户嫌大） | 单独一项「详情卡文字大小」：小 / 标准 / 大 / 特大（85 / 100 / 115 / 130%），在会话小鱼和主肥鱼的「会话小鱼设置」菜单里，挨着「详情卡配色」 |

**数据从哪来**（Claude Code 2.1.309，2026-10-28 实测）：

- **上下文用量**：取会话记录里最近一轮主对话（`isSidechain` 为假）的 `message.usage`，用量 = `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`。压缩之后、还没回复之前，用 `compact_boundary` 记录里的 `compactMetadata.postTokens`。
- **窗口大小**：会话记录、运行清单、桌面版的会话元数据里都没有，所以按模型查（依据 Claude API 文档 2026-10 的模型表）：
  - 1M：Fable / Mythos / Opus / Sonnet / Haiku 5.x，Opus 4.6–4.8，Sonnet 4.6；带 `[1m]` 后缀的也算 1M；
  - 200K：更早的 Claude；
  - 0（只写用量）：认不出的模型。
  - 本机佐证：一个 Opus 5.5 会话在 974,147 tokens 时才自动压缩。
- **VS Code 工作区**：和「跳到对话」用同一套线索（`claude_session_jump.session_workspace`）：
  1. VS Code 自己的状态库记着这个会话开在哪个窗口，就用那个；
  2. 没记，就按目录找包含它的窗口；
  3. 几个窗口都包含时，再用进程启动目录筛。
- **在哪打开的**：`claude_session_info.host_kind`，岛上「最近的对话」也改用这一份，现在认得桌面版了。
  - 程序图标由 `host_icons` 从 Windows 外壳取，有缓存。
  - 桌面版是商店应用：`WindowsApps` 目录列不出来，安装位置从注册表 `HKCU\…\AppModel\Repository\Packages\Claude_*__pzs8sxrjxfjjc` 的 `PackageRootFolder` 查。

**红线 / 不变量**：

- **字体只点一个族**（`ui_fonts` 记录的实测：给 Qt 一串族名，它会把整个字体库映射进进程）：
  - 正文用微软雅黑 UI（Metro 那一代的中文界面字，西文照 Segoe UI 配），标题用它的细体，路径用等宽字；
  - 第一版用了多族列表，第一次打开多花约 250 ms，第二轮改掉；
  - 详情卡不再用等线，`tests/test_ui_fonts.py` 相应改了。
- **配色**：仍由「详情卡配色」的五个方案决定。每个方案加一对 `accent` / `accent_text`，白字对比度全部 ≥ 7，逐项测试。不复用悬停色：「深夜墨蓝」的悬停色是浅灰，当页头会在深色卡片上顶一块白板。
- **新设置**：`agent_link.session_card_text_size`，四档之一，默认 100。手改成别的值、或旧配置里没有这一项时，读配置会改回 100。只在菜单里，和配色同一处（配色也不在设置页）。
- **图标**：单色图标从共用矢量图标库（`context_menus/icons.py`）取，不用 emoji 字体；程序图标取不到就用单色记号。
- **读不到的东西不留空框**：次要信息、上下文、工作区、分支整块不显示。

## 二、修改文件说明

`git diff --numstat 11ebdd6e 03983cb4`：

| 文件 | 增删 | 改了什么、为什么 |
|---|---|---|
| `pet/session_pet_ui.py` | +730 / −106 | 重写 `SessionDetailCard`：页头（程序图标磁贴、来源、标题）、状态、次要信息行（`_MetaChip`）、`_ContextBar`、三行 `_InfoRow`、`TiltButton` 主按钮 + 两个方形图标按钮。还加了：① `_Lines`：按宽度折好行再定高——修实机上被截掉的问题；② `_Elided`：单行省略（工作区名、状态），移上去立刻显示全文，卡片设 `WA_AlwaysShowToolTips`；`_ValueRow` / `_SideScroll`：目录和分支那两行，放在一块磁贴里，左右滑 + 可拖选 + 复制按钮，行首图标（`_RevealIcon`）移上去或点一下弹出整个值；卡片样式表给 `QToolTip` 定字号；③ 纯函数 `phase_line` / `context_text` / `workspace_text`；④ `load_detail` = 读详情 + 认工作区；⑤ 字号由 `_configured_text_size` 决定，菜单改了之后卡片按新字号重搭；⑥ 启动 4 秒后按卡片尺寸预热来源图标；⑦ 会话小鱼菜单加「详情卡文字大小」 |
| `pet/claude_session_info.py` | +63 / −4 | `SessionDetail.context_tokens`、`host`；会话记录里取 usage 和压缩边界；`context_used` / `context_window` / `host_kind`；入口说法加桌面版 |
| `pet/claude_session_jump.py` | +33 / −0 | `session_workspace` / `attach_workspace`：认出 VS Code 会话所在窗口。只对 VS Code 会话、在后台线程里调，读坏了只是少一行 |
| `pet/host_icons.py` | +41 / −1 | 新的来源种类 `desktop`：从注册表的应用包仓库找商店版 `claude.exe`，退路是老的独立安装路径；取不到用 `sparkle` 记号 |
| `pet/context_menus/icons.py` | +31 / −11 | `vector_menu_icon` / `vector_widget_icon` 加可选的 `ink`（调用方自带配色时用，不传和原来一样）；补 `folder` / `branch` / `jump` |
| `pet/ui_fonts.py` | +42 / −0 | `metro_font_family(light)` / `mono_font_family()`：只看字体文件在不在，各给一个族 |
| `pet/session_card_themes.py` | +31 / −0 | 五个方案各加 `accent` / `accent_text`；文字大小四档、`normalize_text_size`、`text_size_choices` |
| `pet/config.py` | +4 / −1 | `agent_link.session_card_text_size` 默认 100，读配置时规范化 |
| `pet/context_menus/shared.py`、`pet/sprite_menu_facade.py` | +14 / −0、+9 / −0 | 主肥鱼菜单的「会话小鱼设置」加「详情卡文字大小」；门面方法 `set_session_card_text_size` 落盘 |
| `pet/claude_session_history.py`、`pet/island_history_panel.py` | +3 / −8、+2 / −1 | 历史行的来源改用 `host_kind`（认得桌面版），图标表加 `desktop` |
| `pet/locale/zh.json` / `en.json` | +26 / −0 各 | 次要信息名称、上下文、工作区、关闭、「Claude 桌面版」、文字大小四档、复制路径 / 分支名 |
| `tests/test_session_card_metro.py`（新） | +561 / −0 | 覆盖：上下文用量与窗口；工作区（VS Code 记录优先、并列时用启动目录、只管 VS Code、读坏不报错）；布局和「读不到就不显示」；五个方案的方角 + 强调色页头；文字大小（默认、落盘、坏值、两处菜单、重开换字号、不跟气泡走）；等宽 + 省中间；次要信息更小；`host` 七种入口（含历史行）；页头用程序图标；注册表找桌面版；长问题 4 行不截、按钮不截（英文）；预热尺寸；目录和分支同一块磁贴、左右滑（含滚轮）、先停最右端、复制按钮进剪贴板并提示；移到 / 点行首图标弹出整个值；悬停提示字号不小于正文、省略的一移上来就显示全文。五轮的新用例在各自修之前都是红的 |
| `tests/test_ui_fonts.py` | +49 / −9 | 对话气泡仍用等线；详情卡改测「各只点一个族：雅黑 UI / 细体 / 等宽」；等宽字的退路 |
| `tests/test_session_card_themes.py`、`test_session_pet_details.py`、`test_session_model_effort.py`、`test_agent_link.py`、`test_host_icons.py`、`test_sprite_menu_parity.py` | 小改 | 强调色对比度；状态行只剩阶段，其余改到次要信息里断言；默认配置多一项；来源种类多一种（预热数 4→5）；「详情卡文字大小」和「详情卡配色」一样是 overlay 独有的菜单项 |

没有改动：跳转逻辑、配置文件格式之外的设置页、会话小鱼本身。

## 三、性能分析

**方法**：在仓库根目录用 `.venv\Scripts\python.exe`，`time.perf_counter` / `timeit` 计时，RSS 用 `psutil`，`QT_QPA_PLATFORM=windows`（真实字体与 DPI）。新旧卡片各开一个新进程测。环境：Windows 11 Pro 26300，Python 3.13，PySide6，Claude Code 2.1.309。

| 指标 | 实测 | 触发频率 |
|---|---|---|
| `parse_transcript_tail`（512 KB 真实会话记录，多取 usage 和压缩边界） | 2.9 ms / 次（20 次均值） | 点开详情卡一次，后台线程 |
| `load_detail`（真实桌面版会话） | 中位 4.3 ms，最大 16.7 ms（n=10） | 同上 |
| `attach_workspace`（真实 VS Code 记录：2 个窗口，一个是 7 个文件夹的 WSL 工作区） | 中位 27.5 / 28.9 ms（各 n=5） | 只有 VS Code 会话，点开时一次，后台线程 |
| 注册表找桌面版安装位置 | 1.4 ms | 取桌面版图标时一次（结果缓存） |
| 桌面版图标第一次从外壳取 | 360 ms；之后读缓存 0.05 ms | 每个进程一次，在启动 4 秒后预热里付，不在点击时付 |
| 首次构造 + 填充 + 显示 | 新 139–168 ms，旧 54–131 ms（各 3 次） | 每个进程一次（卡片复用） |
| 再次填充 | 新 2.6–3.4 ms，旧 1.4–4.0 ms | 每次点开、读完详情时 |
| 首次打开的 RSS 增量 | 新 +29.6–30.1 MB，旧 +12.8–16.1 MB | 每个进程一次 |

**RSS 多出约 15 MB 的原因（已拆开）**：

- 同一张新卡片：页头**不放程序图标**时 +13.4 MB，和旧卡片一样；放图标时 +29 MB。多出来的是第一次用 `QFileIconProvider` 向 Windows 外壳取图标时，外壳组件加载进进程。
- 字体不是原因：标题不用细体、路径不用等宽字、整张换回等线，都在 +28–29 MB。
- 运行中的桌宠里，岛上「最近的对话」启动后本来就会用同一个 `host_icons` 预热这几种图标，外壳早已加载，详情卡基本不再新增内存。没开那个列表时，由详情卡的预热付这一次。

**第一次打开慢的原因**：第一版给了多族字体列表，首次多花约 250 ms（对照实验：先用同样字体显示一次中文标签，就降到 60 ms）。第二轮改成单族后回到上表的量级。

**结论**：
1. **稳态开销**：没有。新代码只在点开详情卡时运行；唯一的新定时器是启动后 4 秒的一次性图标预热，没有轮询。
2. **新路径的成本**：
   - 会话记录多取两个字段（同一遍扫描）；
   - VS Code 会话多认一次工作区（约 28 ms，后台线程）；
   - 来源图标一次性 360 ms，放在启动后的预热里。
3. **新的系统调用 / 磁盘 / 网络 / 线程**：
   - 注册表：读一次 HKCU 的应用包仓库；
   - 外壳：取程序图标；
   - 磁盘：VS Code 会话读 `storage.json` / `workspace.json` / `state.vscdb`（只读，就是跳转本来要读的文件）。
   - 不联网，不新增线程。
4. **内存**：
   - 卡片多十来个子控件和几张 11–22 px 的图标位图，卡片仍复用；
   - 外壳组件一次性约 15 MB，和岛的历史列表共用，说明见上。

## 四、实机运行记录

本机：Windows 11 Pro 26300，三块屏；Claude 桌面版 4.29（商店版）；桌宠从源码运行（`run.bat`）。每一轮都把提交快进到主检出、重启桌宠：`pet-overlay-gate.log` 里依次是 `20:13:25 pid=47148`、`20:17:51 pid=46224`、`20:35:57 pid=49528`、`20:37:50 pid=46444`、`20:42:29 pid=51272`、`20:48:13 pid=43528`、`21:06:30 pid=40440`。

**第一轮**（Metro 改版）：用户点这个会话的小鱼，截图里卡片已是 Metro 风格。用户提了几条：字太大要能调、路径要等宽、模型那几项太显眼、来源要有程序图标；截图里的长问题和按钮字被截掉了。

**第二轮**：用户截图里看到：
- 页头是 Claude 桌面版自己的图标 +「Claude Desktop」；
- 「Your turn」下面一行灰色小字「Opus 5.5 · high · 1 min」；
- 「CONTEXT 446k / 1M · 45%」；
- 最近的问题完整显示 4 行、末尾省略；
- 路径和分支是等宽字、省中间；
- 「Jump to chat」完整，旁边两个方形图标按钮。

用户回复「looks nice」，只剩一处：路径和分支省略后要能看到全文。

**第三轮**：省略了的那一行移上去立刻显示全文。用户回复「看到了」，又提了两点：路径和分支放在一个窗口里、能左右滑，或者至少提示里能复制；提示的字太小，要不小于原来。

**第四轮**：目录和分支放进同一块磁贴，左右滑、可拖选、每行一个复制按钮；悬停提示的字号不小于正文。桌宠重启：`20:48:13 pid=43528`。用户回复「很好」，再加一个功能：点或移到路径前的图标就显示整个值，只想看一眼时不用拖滚动条。

**第五轮**：行首的目录 / 分支图标改成手形光标，移上去就贴着它弹出整个值，移开收起，点一下也弹。桌宠重启：`21:06:30 pid=40440`。

**用户确认**：第五轮之后用户在实机上试过，回复「可以，开 PR」。第二、三轮的确认见上（「looks nice」「看到了」「很好」）。

**真实数据**：
- 对这个会话调 `load_detail`：来源「Claude 桌面版」，Opus 5.5，high，上下文 297k / 1M · 30%（第二轮截图时已到 446k）。
- 用本机 VS Code 当时开着的两个窗口（都在 WSL 里，一个是 7 个文件夹的工作区，一个是单文件夹）调 `attach_workspace`，两个都认对了。窗口名从略。

**截图**：五个配色方案、四种来源（桌面版 / VS Code / WSL 终端 / Windows 终端）、中英文都用真实字体渲染看过，亮暗都有，没有截断或重叠。

**没在实机验证的**：没有跑在 VS Code 插件里的 Claude Code 会话，工作区那一行没在真实卡片上看到。数据那一步已用真实 VS Code 记录核对过，界面那一步有单元测试。

**测试**：
- 详情卡、配色、会话、跳转、图标、字体、文案、配置相关的测试都通过；
- ruff 通过，`git diff --check` 通过；
- **最终全量**（`03983cb4`，本机 12 分 04 秒）：5863 通过、14 跳过、5 失败，只剩下面这 5 条基线失败。
- 中途一次全量（`9c04ba36`，14 分 28 秒）：5859 通过、14 跳过、8 失败。
  - 3 条是 `test_sprite_menu_parity`：主肥鱼菜单多了「详情卡文字大小」，没登记进 overlay 独有条目。`331bc658` 补上后，菜单相关 145 例通过。
  - 其余 5 条是基线失败，在基线 `11ebdd6e` 上同样失败：`test_image_directory_picker_opens_right_drawer_with_three_column_masonry`、`test_catalog_animation_count_guard_survives_optimize`、`test_festival_id_guard_survives_optimize`、`test_real_second_process_refused_on_overlay_topology`、`test_capture_window_rect_coordinates_and_clamping`。
