# PR 报告：上游挑拣同步（agent-link / 设置窗提速 / 聊天窗七步 / 帧序列 v6）

> **基线**：`28cb4f0e`（fix(briefing): 放行 Atlassian 插件的只读入口）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-24
> **范围**：34 个文件（实现 16、测试 18、文档 0）；`git diff --shortstat 28cb4f0e..HEAD` = +2869 / −211
> **关联**：上游 `MerZlin/dsh-pet-indesktop` v4.3.0 → v4.4.0（分叉点 `ee699c7b` 之后 311 个提交）；
> 逐项对应的上游提交写在每个小节里

## 一、核心特性

上游一周发了五个版本，`git merge-tree` 与本分支有 **130 个文件冲突**（上游把 10 个模块改成目录包，
我们删了打包 / 更新器、改名、i18n、Metro 设置页），整体合并不可行。本轮按功能挑拣：用户点名
要的四件（设置窗提速、agent-link、聊天窗、素材画质）加上三个干净的 cherry-pick，每一步一个提交、
先把上游测试搬来改成红再动代码。

| # | 能力 | 用户看到什么 |
|---|---|---|
| 1 | agent-link 完成确认定时器回收 | 长跑一天不再按回合数攒已停表的 QTimer（每轮一个） |
| 2 | 待办：daily 跨午夜提前提醒、落盘失败不算保存成功 | 提醒不迟发；保存失败会报出来 |
| 3 | 设置窗打开提速 | 点「肥鱼设置」不再先闪一个无标题小窗；构造中位 5366 → 855 ms |
| 4 | 聊天窗：末条下方不留空白、重开回到最新回复 | 几十轮对话后窗口底部不再空一大块 |
| 5 | 聊天窗：AI 回复按 Markdown 渲染（现代窗 / 经典窗 / 快捷气泡 / 岛气泡） | 表格、代码块、列表、链接正常显示；复制按钮复制原文 |
| 6 | 聊天窗：输入框粘贴 / 拖拽图片与文件 | Ctrl+V 截图直接成附件 |
| 7 | 聊天窗：时间感知 | 模型知道现在几点、距上条消息隔了多久 |
| 8 | 聊天窗：关闭即销毁，Esc 也走完整收尾 | 关窗后控件树与内存真的还回去（RSS −23 MB） |
| 9 | 岛对话退出时不再整份覆盖保存 | 完整聊天窗里已落盘的新消息不会被旧快照盖掉 |
| 10 | 帧序列档位 v3 → v6 | 白色桌面上整只鱼的浅灰矩形消失；帧序列改无损，没有 q70 压缩噪点；多宠同播缺帧少 |

**红线 / 不变量**：聊天会话文件格式不变（时间标记只在发给模型时附加）；`effective_system_prompt`
不变（文件解读等不带工具的请求照旧）；用户气泡永远纯文本；`WA_DeleteOnClose` 仍为 False（销毁
时机由 lifecycle 判定，不能赶在在飞 worker 之前）；素材源视频一个字节没动（上游与我们逐字节相同）。

**有意不搬的**（原因见各条）：截图提问（随包 30 MB OCR + 打包链，我们有 Claude 识屏）；素材包市场 /
720p 几何 / `library.py` 的 pack 部分（我们自有素材）；每屏一窗多屏（我们自己做了 `overlay_viewport`，
三屏都 125% 没混合 DPI 问题，上游这条线反复了三次）；TTS 后端注册表、每日一签、天气、DSH 修复、
Android、全局记忆（我们走 AI-Base 知识库）；聊天分页、深度思考 / 联网搜索（Claude 通道自带 effort）；
「回收内存」菜单——它 `EmptyWorkingSet` 的是**别的进程**，不减桌宠自己的内存（桌宠自己的瘦身
214 → 156 MB 在分叉前就有了，我们已经带着）。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/agent_link.py` | +7 / −1 | `_fire_done` 自然到期也 stop + deleteLater（上游 dce895ff，cherry-pick） |
| `pet/todo_reminder.py` | +47 / −13 | daily 跨午夜的提前提醒按「下一次触发」算（上游 9be653d1，cherry-pick） |
| `pet/todo_panel.py` | +33 / −7 | 条目落盘失败不再当成保存成功（上游 fd117195，cherry-pick） |
| `pet/chat/ai_settings_page.py` | +13 / −8 | `appearance_rows` 的 7 行传 `parent=self`：构造期 `_update_background_visibility` 对无父行 `setVisible(True)` 会当场开出顶层窗口（上游 a8bc79e3 的我们这一半；另一半 `settings_network.py` 我们没有那个模块） |
| `pet/chat/widgets.py` | +206 / −19 | 气泡纵向策略 Minimum → Preferred + `showEvent` 滚到底（9cc8e4c2）；`MessageBubble` Markdown（`content` 属性、`set_content(markdown=)`、流式节流定时器、复制原文，c33be7d3）；剪贴板图落临时 PNG、`insertFromMimeData` / 拖内存图（e969c38e）；`done()` 统一收尾 + `release_window_when_idle`，closeEvent 只转发（833b053d + cee01e0e）；关窗前先落库未排空的回复（ed78e6e8 X3）；request id 先落再 send（ed78e6e8 F6）；5 秒提示复位定时器带上下文对象 |
| `pet/chat/legacy_widgets.py` | +33 / −7 | `_set_body_text` 助手走 Markdown（5b9b39a3）；`done()` / closeEvent 同现代窗；F6 |
| `pet/chat/markdown_view.py` | +542 / 0 | 新文件，取上游 main 最终版（md4c GitHub 方言、`MarkdownNoHTML`、单换行保留、裸 URL 显式 autolink、表格前补空行、场景扮演动作段 token 化） |
| `pet/chat/lifecycle.py` | +74 / 0 | 新文件：`release_window_when_idle`——没有在飞 worker 立刻 deleteLater，否则等 worker 的 finished 再删；销毁前 `service.detach()` |
| `pet/chat/service.py` | +18 / −1 | `has_running_workers()`、`detach()`、`_current` 在 detached 时恒 False |
| `pet/chat/prompt.py` | +48 / −2 | 时间感知：`format_time` / `format_elapsed` / `stamp_message` / `stamp_text` / `time_context`，`build_messages(now=)`；文案走 `chat.time.*` |
| `pet/quick_chat.py` | +14 / −2 | `_set_output_markdown`：全文与分页两条显示路径都走 Markdown |
| `pet/app.py` | +49 / −19 | `_chat_window_usable` / `_own_chat_window` / `_forget_chat_window`；`open_*_chat` 按 `shiboken6.isValid` 判槽位；`_present_dialog` 对已销毁对象直接返回；「退出这只」不对 lifecycle 接管的窗口补 deleteLater；退出时不再整份保存岛对话会话（e3807027 H1） |
| `pet/locale/zh.json` / `en.json` | +7 / 0 各 | `chat.time.*` 七个键 |
| `pet/frameseq_provision.py` | +161 / −61 | v5：反解链尾 `floor_faint_alpha` 把 `a == 1` 清成全透明（53d0587f）；v6：阶段二 `lossless=True, exact=True, method=2`，单帧失败整段作废，`ENCODER_DESC` / `UNBLEND_MARK` 改档（19800293 的这一部分） |
| `pet/frameseq_clip.py` | +27 / −14 | 预取线程 1 条 → 3 条轮转，退出先全部 quit 再逐个 wait |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_agent_link.py` | +35 / 0 | `test_fired_done_timer_is_recycled`：5 轮自然到期后 `findChildren(QTimer)` 不增长（改前红） |
| `tests/test_todo_reminder.py` | +162 / 0 | 上游随 cherry-pick 带来的用例（跨午夜 / 落盘失败） |
| `tests/test_modern_settings_rows_topwindow.py` | +112 / 0 | 监视构造期真实到达的 `QEvent.Show`：有 `SettingRow` 以顶层窗口身份被显示即红（改前红 2 / 改后绿 2） |
| `tests/test_chat_timeline_scroll.py` | +99 / 0 | 长对话打开即落在最新回复、下方空白 ≤ 80px；重开（重新构造窗口）回到底部（改前红 2） |
| `tests/test_chat_markdown.py` | +132 / 0 | 围栏 / 缩进代码块、表格、原始 HTML 转义、气泡渲染但复制原文、流式节流、经典窗（改前红 3） |
| `tests/test_chat_composer_paste.py` | +165 / 0 | 粘贴图 / 粘贴文件 / 纯文本 / 拖内存图 / 只清自己的缓存文件（改前整文件 import 失败） |
| `tests/test_chat_time_awareness.py` | +143 / 0 | 历史与本轮消息带标记、间隔句、连续对话 system 逐字不变、about_user 位置、英文文案、旧会话文件不被改写（改前 import 失败） |
| `tests/test_chat_window_lifecycle.py` | +365 / 0 | 上游版：关闭即销毁、解除位置监听、开着时复用、重开能发消息、反复开关不漏控件、流式中关窗仍销毁、Esc 完整收尾；跳过依赖聊天分页 / 记忆功能的 3 条 |
| `tests/test_frameseq_alpha_floor.py` | +240 / 0 | v5 底板清理（真 ffmpeg + 真素材三帧：`a == 1` 归零、`a ≥ 2` 逐位不变） |
| `tests/test_frameseq_provision.py` / `_clip.py` / `_unblend_v4.py` / `_prefetch_watchdog.py` | +93 / −44 | 档位串、无损参数、单帧失败整段作废、三线程池 |
| `tests/test_chat_subsystem.py` / `test_about_user_prompt.py` / `test_file_interpret.py` / `test_quick_chat.py` / `test_island_chat.py` | +37 / −17 | 断言跟着 `content` 属性、时间标记、Markdown 渲染调整；快捷气泡新增 1 条 |

### 未改动

- `pet/library.py`：上游 v6 同一提交里的 285 行是素材包市场 / sourceless 库 / 几何根，本仓库不搬。
- `scripts/check_frameseq_bundle.py`、`AGENTS.md` 的帧序列门：那是打包期硬门，本仓库 2026-10-11 起不打包。
- `pet/settings_network.py`：本仓库没有岛网络指标，上游设置窗提速的那一半无从移植。

## 三、实现要点

- **时间感知的落点和上游不同**：上游把「当前时间」写进 system。本仓库的 Claude 通道对 system /
  消息前缀开着提示缓存（`anthropic_provider.py` 的 toolset 断点 + 顶层自动缓存），system 每分钟变
  一次会让整段历史每轮重新写缓存（写 1.25× vs 读 0.1×）。改成：本轮用户消息和历史消息带同一种
  `[2026-10-24 周五 15:00]` 标记，system 只放说明 + ≥10 分钟的间隔句——连续对话里 system 逐字不变
  （`test_continuous_conversation_keeps_the_system_prompt_stable` 钉住）。代价：出现新间隔那一轮缓存失效一次。
- **关闭即销毁**：两套窗口把收尾统一挂在 `QDialog.done()`（X / Esc / reject 的公共出口），closeEvent
  只转发——Esc 走 `reject() → done()` 不经过 closeEvent，只写 closeEvent 会让 Esc 留下指向已销毁
  窗口的位置监听器。销毁由 `lifecycle.release_window_when_idle` 判定：`QThread` 运行中被销毁会崩进程，
  所以有在飞 worker 时等它的 `finished`；连上之后再复查一次，补「判定忙碌」与「建立连接」之间退出的窗口。
  app 层槽位在 `finished` 里清空（直连，先于 deleteLater）。
- **Markdown 流式节流**：单次渲染 + 排版超过 8 ms 时合并进 50–250 ms 的定时器（上游 6000 字实测
  20.6 ms，超过打字机 18 ms 一拍就卡）；离开流式立刻渲染终稿。
- **帧序列 v6**：反解链与 v5 逐位相同，只改编码参数；`exact=True` 是硬要求（libwebp 默认会改写
  `alpha == 0` 像素的 RGB）。改档位串即让 101 个 v3 世代全部失效——运行时的迁移配额是**每次启动 1 个
  clip**（`MIGRATION_CLIPS_PER_ROUND`），所以全量重出走 `tools/convert_frameseq.py`（见第五节）。

## 四、性能分析

**方法（可复现）**：探针脚本在会话 scratchpad（`time_settings.py` / `probe_chat_close.py`），
都是真 `windows` 平台插件、隔离 APPDATA；对照组是 `git worktree add --detach <path> <sha>`。
环境：Windows 11 Pro 26300，Python 3.13，PySide6（仓库 `.venv`），三块 125% 显示器。

| 指标 | 实测 | 归属 |
|---|---|---|
| 设置窗构造（`ModernSettingsDialog(config, include_ai=True)`，n=5，排除首轮冷加载） | 中位 **5366 ms → 855 ms**（min 4873→840，max 5531→892）；构造期游离顶层行 1/次 → 0 | 既有热路径 |
| 聊天窗开→关（120 条消息的会话，真平台）| 改前：关后 1261 个控件全部存活、RSS +0.1 MB、`shiboken6.isValid`=True；改后：窗口销毁、控件 −1021、RSS **−23.4 MB** | 既有路径 |
| agent-link 每轮完成确认 | `findChildren(QTimer)` 5 轮后不增长（改前每轮 +1） | 既有热路径 |
| Markdown 渲染 | 上游实测 6000 字 20.6 ms / 次；节流阈值 8 ms，定时器 50–250 ms | 新增，每次回复文本变化触发 |
| 帧序列 v6 编码 | 上游实测 method=2 为 83 ms/帧（method=6 要 610 ms）；本机全量重出结果见第五节 | 一次性 |
| 帧序列预取线程 | 1 → 3 条常驻 QThread | 新增线程，进程级共享 |

**结论**：① 稳态开销：设置窗构造 −84%；聊天窗关闭后内存真的归还；agent-link 不再按回合攒对象；
其余稳态路径不变。② 新增路径：Markdown 渲染每次回复文本变化一次（≤ 20 ms，超 8 ms 合并到定时器）；
时间标记只是字符串拼接；剪贴板图落盘只在粘贴 / 拖图时发生。③ 新线程：帧序列预取 +2 条常驻线程；
无新的网络请求；新增磁盘写：粘贴图的临时 PNG（24 小时懒清扫）、帧序列一次性重出。④ 内存：无损帧
序列比 q70 大（上游口径「多几十 MB 缓存，有硬上限」），本机数字待重出完成后补；聊天窗不再常驻。

## 五、实机运行记录

本机真实环境（不是 CI、不是 mock），桌宠从源码跑（`run.bat` → `BigFish.exe`）。

- **设置窗闪小窗的现场复现**：`time_settings.py` 指向改前 worktree（`cd2b40a3`），真 `windows` 平台，
  输出 `n=5 median=5366ms ... free_rows_per_build=[1, 1, 1, 1, 1]`；改后同一脚本
  `median=855ms ... free_rows_per_build=[0, 0, 0, 0, 0]`。
- **聊天窗关闭不还内存的现场复现**：`probe_chat_close.py` 指向 `28cb4f0e` 的 worktree：
  `closed: rss=176.8MB widgets=1261 window_alive=True`；改后：`closed: rss=155.8MB widgets=240 window_alive=False`。
- **agent-link 泄漏**：`test_fired_done_timer_is_recycled` 在 `28cb4f0e` 的 worktree 上 1 failed，主树 passed。
- **帧序列**：重启桌宠后日志 `pet-2920.log` 每轮供给都是「新转 0 / 跳过 0 … 帧序列映射 0 段」，只有
  1 个目录升到 v6——证实运行时迁移配额是每启动 1 个 clip（上游也是靠构建期 CLI 全量重出的）。
  于是以 BelowNormal 优先级跑 `tools/convert_frameseq.py --character shenshen --include random,events`
  与 `--character claude`（结果见本节末尾的追记）。重出期间桌宠回退 WebM 播放（日志里的
  `webm 圈边界宽限期满未续圈，reader 退出` 就是那条路），功能照常。
- **桌宠重启**：`pet-overlay-gate.log` 新增 `acquired pid=2920`；启动日志无 Traceback；
  设置窗、简报窗照常。
- **没有自动验证的**：聊天窗里 Markdown 表格 / 代码块的真实观感、粘贴截图成附件、时间标记对模型回复
  的影响——需要真的发一轮对话（会花个人 key 的额度），留给用户在实机点一次；本报告不冒充做过。

**测试**：每一步的聚焦族见第二节；chat 相关 8 个文件 186 passed / 4 skipped，触及聊天窗的另 9 个文件
165 passed；frameseq / library / webm / move_sync 18 个文件 372 passed；设置相关 17 个文件 157 passed；
ruff 全绿。全量套件在隔离 worktree 里跑，结果见追记。

## 六、追记（2026-10-24 晚）：全量套件与素材全量重出

**全量套件**（隔离 worktree `git worktree add --detach … HEAD`，`QT_QPA_PLATFORM=offscreen`，临时 APPDATA）：
**8 failed / 5633 passed / 14 skipped，672.89 s**。8 条里 4 条是本机既有基线失败（`test_image_directory_picker_*`
路径超 260、`test_festival_id_guard_survives_optimize` 与 `test_real_second_process_refused_*` 子进程输出按
cp1252 解码、`test_capture_window_rect_*` 多显示器负原点，见仓库里以往报告），另 4 条是测试断言没跟上本轮
改动——`test_convert_frameseq.py` 两条还断言产物是有损（上游同一提交里已改成 `VP8L` 全无损，照搬）、
`test_second_batch.py` 快捷气泡读的是渲染后的 HTML（改成 `QTextDocument.toPlainText` 比对，上游 14885bbf
同款）、`test_overlay_chat_proactive.py` 期望本轮用户消息不带时间标记——四条修后 3 个文件 28 passed（`dc7af8e1`）。

**素材全量重出**（`tools/convert_frameseq.py --character shenshen --include random,events` + `--character claude`，
BelowNormal 优先级，桌宠停着）：**新转 98 / 跳过 8 / 失败 0，67.7 分钟**（上游口径 106 clip 73m53s）；
磁盘账 webm 54.4 MB → webp 1475.9 MB（27.1×），`shenshen/frameseq` 实占 **1408 MB**（v3 有损时 442 MB，
无损是它的 3.2 倍）；重出后 101 / 101 个世代目录都是 `unblend-white-v6`，没有 `.tmp` 残留。
解码后的帧是 RGBA 位图，大小与编码档无关，所以**运行时内存不因无损而涨**——只有磁盘涨。

- 第一次重出时桌宠还开着，它的后台供给把不认识的 `.tmp` 目录当半成品清掉，3 个 clip
  作废（`半成品目录无法清理: WinError 32` / `No such file`）；停掉桌宠重跑后 0 失败。
  **结论：改档位串后的全量重出必须在桌宠停着时跑 CLI**，运行时迁移配额（每启动 1 个 clip）只适合
  零星补转。
- 重启桌宠（`acquired pid=13060`）：首轮供给「本轮无事可做，帧序列映射 **106 段**」，没有 WebM 回退
  reader、没有 ffmpeg 子进程；WS 326 MB，20 秒 CPU 均值 0.84%（全核口径）。
- 抽 3 张 v6 帧验像素（idle / click 各一两张）：RIFF chunk 都是 `VP8L`（无损），`alpha == 1` 像素
  **0 个**、`a == 0` 占 83–84%（v3 时整帧 82% 的底板是 `a == 1`——白色桌面上那块浅灰矩形的来源）。

## 七、追记（2026-10-24 晚）：用户反馈「连点鱼卡住没反应」——第一次重出撞车留下的两个缺头目录

**现象**：重出后用户连点鱼，几秒没反应。日志 `pet-13060.log`：7 次点击伴随 24 条
`frameseq 预取超时 528ms：clip=点击回应-害羞惊讶… frame=1 wanted=1 pending=0 thread_alive=True`，
每三次「降级同步加载」，`tick 间隔 … max=565.0ms`（同步直读也拿不到帧，静默返回）。
两个 clip 受害：`点击回应-害羞惊讶`、`点击回应-元气挥手`。前几天的日志（10-22 115 次点击、10-23 133 次）
0 条预取超时——是本轮引入的。

**排查**：先怀疑新加的 3 条预取线程。用真素材 + 真 `FrameSeqClip` 写探针（`probe_click_clip.py`，模拟
连点 7 次）：`PREFETCH_THREADS=3` 与 `=1` **都**复现——`cur=0 awaiting=1 wanted=1 pending=0`，帧 1 永远不来。
排除线程池。列目录：`害羞惊讶` 只有 `f_0017…f_0241`（225 个），`元气挥手` 只有 `f_0138…`（104 个），
而 `meta.frames` 分别写着 225 / 104——**个数自洽，编号不从 1 开始**。`_FramePaths[1]` 现推出的
`f_0002.webp` 不存在，worker 解出空帧，`_on_loaded` 按「坏帧」静默返回；看门狗的同步直读同样空帧、同样静默。
全部 101 个目录审计：坏的只有这两个，都是第一次重出（桌宠开着）19:10–19:11 那个撞车窗口里发布的：桌宠的
后台供给把 CLI 的半成品 `.tmp` 当残留清掉了前面几十帧，CLI 收尾按磁盘个数写 meta，目录看起来完整，
第二次重出按「同档已完整」跳过了它们。

**修法**（`cf7cbe0b`）：`frame_ends_present()`——`_complete_meta`（采纳闸门）与 `convert_clip`（发布前）
都要求 `f_0001` 与 `f_<frames>` 真在磁盘上（两次 `stat`，与数个数同级）。新用例
`test_generation_with_a_hole_at_the_start_is_not_complete`（缺头 / 缺尾两种）改前红、改后绿；
frameseq / convert / library 族 **241 passed**。两个坏目录删掉后停桌宠重转：`新转 2 / 跳过 9 / 失败 0，93 s`，
现在都是 `f_0001..f_0241`；桌宠重启后首轮「帧序列映射 106 段」，探针再跑帧 1 正常到货（见下）。

**没做的**：看门狗对「同步直读也是空帧」仍然静默——那条路以后至少该记一次 WARNING，本轮没动
（它不是根因，改它要连带看门狗的节流口径）。

## 八、追记（2026-10-24 晚）：简报 / 笔记 / Slack 关注的提示词明文可改、effort 可选、三级优先级

用户反馈「设置里没有简报的配置项」——其实在「自动化与联动 → 工作简报」（开关 / 只在工作日 / 几点 /
模型 / 来源），但发给 AI 的提示词是黑箱、effort 写死、没有优先级。两个提交（`b1ad9fa4`、`7f8a2c93`）：

- **提示词明文可改**：三节各加一行「发给 Claude 的提示词」——预填内置模板（简报的按当前来源开关拼出来），
  占位符发送前替换（简报 `{now} {hours} {prs} {priority_rules}`、笔记 `{now} {original} {language}`、
  Slack `{now} {since} {max_items}`）；和内置一字不差存空串（跟着以后的版本更新）、改过整份存
  （简报 / 笔记按界面语言 `prompt_zh` / `prompt_en`，Slack 一份 `prompt`）；「恢复内置」。
  渲染不用 `str.format`（用户文本里的 JSON 示例花括号会炸，而要求写 `{{` 会让编辑框里的字和真正发出去的不一样），
  `work_briefing.render_template` 只换认识的占位符；笔记 / Slack 内置模板里原先的 `{{` 转义一并去掉。
  取舍：简报改过模板之后，来源开关只管 Claude 能用哪些工具，提示词里要不要提某个来源由用户自己写——
  提示里写明了。
- **effort**：三节各加「思考强度」（low / medium / high / xhigh，默认 high = 那个账号原来的默认），显式传
  `--effort`；`normalize_effort` 只认四档（它会拼进 shell 命令）。
- **三级优先级**：内置提示词多一段「优先级」——每条行首 ★★★（今天必须处理）/ ★★（本周内）/ ★（知悉即可），
  由模型按紧急程度、截止、是否有人在等定，日程行不标；bug 行 `- ★★★ 🐞 [编号]`。窗口 `_decorate` 按星数上色
  （白天 / 黑夜各一套 `p1/p2/p3` 令牌，★★★ 加粗），bug 底色照旧（检测时先跳过行首的星）。
  设置页加「优先级偏好」多行框，非空时作为「我的优先级偏好（优先于你的判断）：…」追加进 `{priority_rules}`
  ——这就是用户说的「以后加自己的偏好」，现在就能写。
- 共用部件 `settings_prompt_editor.PromptEditor`（多行框 + 恢复内置，口径同语音报时的内置台词库）。

**测试**：`test_work_briefing_prompt_editing.py` 10 条、`test_prompt_editing_notes_slack.py` 7 条、三处设置页
各 1–3 条新用例，全部先红后绿；简报 / 笔记 / Slack / 设置相关 15 个文件 **175 passed**；ruff 干净。
**实机**：真 `windows` 平台截图（隔离 APPDATA）「自动化与联动」整页，三节的「思考强度」「发给 Claude 的提示词」
「恢复内置」都在位，提示文案换行正常（`settings-shots/automation-zh.png`，会话 scratchpad）。
**用新提示词真跑一次简报**（本机 WSL、公司账号、sonnet、effort high，结果存进桌宠的 `work-briefing.json`）：
22 轮、148.8 s、输入 419k / 输出 20k tokens、$1.08（上一版同口径 21 轮 / 135 s / $0.92——多出来的是每条的星级判断）；
0 个工具被拒。星级分布：Jira ★★★ 1 / ★★ 13 / ★ 14，PR ★★ 9 / ★ 11，Slack ★★ 1 / ★ 1，「Do first」第一条
是 `★★★ 🐞` 那个 High 级 bug（工单号从略）——模型没有把所有 bug 都标成 ★★★（15 个 bug 里只有 1 个三星），说明它确实在按紧急程度
判而不是按类型。窗口里星按级别上色（真平台截图 `saved-light.png` / `saved-dark.png`，会话 scratchpad）。
**注意**：设置窗口是独立进程——用户当时开着的那个还是旧代码，看不到新行，关掉重开才有；旧窗口里点保存
会把新键丢掉（旧 normalize 不认识）。

## 九、追记（2026-10-24 晚）：新一级域「简报与笔记」

用户：简报这些放到设置第一层，名字体现「定时向 AI 发请求 / AI 协助的笔记」。提交 `62f83fac`：
- `SETTINGS_DOMAIN_NAV` 加 `("简报与笔记", "briefing")`，位置在「AI 与对话」之后、「自动化与联动」之前；中文名是
  内部标识（`select_page("简报与笔记")` 在英文界面下照样认，显示为 "Briefings & notes"）；侧栏图标一页纸 + 三行字 +
  一颗星（呼应三级优先级的星）。
- 页面顺序：折叠说明「这一页是什么」（共同点：按时向 Claude 发一次**只读**请求；谁在干活——三个走 WSL 里的工作账号、
  个人助理走个人 key；你能改什么；结果放哪）→ 工作简报 + 怎么运作 → Slack 关注 → 工作笔记 + 怎么运作 → 个人助理 +
  怎么运作。「自动化与联动」只剩 Agent 联动、VS Code 工作区、通知中心、文案风格、台词。
- `SettingsSection.title` 新属性：页面组织与测试按它认节，不再去抓标签控件。
- 取舍：没有给旧位置留别名或搜索重定向——设置搜索本来就按行索引、与页面无关，搜「简报」照样命中。

**测试**：新增 2 条（页面归属与顺序、英文名）先红后绿；9 个钉着侧栏顺序 / 节归属的既有测试改成新顺序
（`test_menu_layout` 两处、`test_architecture`、`test_desktop_pet_features`、`test_settings_interaction_tabs`、
`test_settings_english`、四个功能节的设置测试）；设置相关 14 个文件 **194 passed**；ruff 干净。
**实机**：真 `windows` 平台截图（隔离 APPDATA）整扇设置窗停在「简报与笔记」页，中 / 英各一张
（`settings-shots/domain-briefing-zh.png` / `-en.png`，会话 scratchpad），侧栏 10 项顺序与测试一致。
## 十、补记：同日早些的三个简报提交（当时没写报告，开 PR 前补齐）

`dbc23f44` **bug 单置顶 + QA 场景**：Jira 分两次查——先查 bug（最多 20 条），再查其余（最多 15 条、排除 bug），
bug 不再被「最多 15 条」挤掉；bug 行以 🐞 开头，下面附一行「QA 报的场景」（报告人、环境、步骤、实际 / 预期，有来回推时
写 QA 最后怎么说）；概要先提 bug，「建议先做」bug 排前；窗口里 🐞 行及其场景行画浅红底（白天 / 黑夜各一令牌）。
`e23da32a` **用量栏**：「生成于」下面一条图标栏——模型、effort、用时、输入 / 输出 tokens、花费（复用笔记的 `NoteMetaBar`，
加 `keys` / `framed` / `show_values`，新增仪表盘图标）；`claude -p` 显式传 `--effort high`（结果 JSON 不报 effort）；
Briefing 多 model / effort / tokens_in / tokens_out / cost_usd 并落盘。
`28cb4f0e` **Atlassian 插件只读入口**：放行 `discover` / `executeRead`（实机读 bug 评论被拒，QA 最后的回复就丢了），
同组 `executeWrite` / `executeDestructive` 仍拒绝，Jira 关掉时也不放行。

**修改文件说明**：`pet/work_briefing.py`（提示词、工具名单、Briefing 字段）、`pet/work_briefing_ui.py`（底色、用量栏）、
`pet/note_meta_bar.py`（泛化）、`pet/locale/*.json`、`scripts/capture_briefing_window.py`（示例加一条虚构 bug）；
测试 `tests/test_work_briefing_bugs.py`（12 条）、`tests/test_work_briefing_usage.py`（7 条），改前红。
**性能分析**（本机 WSL 真跑，公司账号，sonnet）：改前 7 轮 / 79 s / 3 条 bug 可见；bug 分查 + 逐条读评论后
23 轮 / 176 s / 12 条 bug；放行只读入口后 21 轮 / 135 s / 413k 输入 token / $0.92（0 个工具被拒）。多出来的都是逐条
`getJiraIssue`——是功能本身的代价，不是回归；窗口侧上色是一次 `setMarkdown` 后遍历文档块，毫秒级。
**实机运行记录**：三次真实简报的结果都存进了桌宠的 `work-briefing.json`、窗口截图核过（bug 底色、用量栏、英文界面）；
第一次放行前 `denied=['…discover', '…executeRead']`，放行后 `denied=[]`，每条 bug 带上了 QA 最后一条评论。

**合并前全量**（隔离 worktree，HEAD = `62f83fac`，含另一个会话同期的仪表盘 / 岛磁贴 5 个提交）：
**4 failed / 5698 passed / 14 skipped，736.58 s**；4 条全是本机既有基线（路径超 260、两条 cp1252 子进程输出、
多显示器负原点），与第六节那次相同。
