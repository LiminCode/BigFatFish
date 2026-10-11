# PR 报告：Claude Code 会话小鱼、Claude 通道、跨屏、BigFish 身份与一批体验改动

> **基线**：`658e586`（main：Claude Code 联动提速、多会话收敛、审批提醒与 WSL 通道）
> **分支**：`feature/claude-session-fish`　**日期**：`2026-10-11`
> **范围**：144 个文件，+18613 / −1541（`git diff --shortstat origin/main..HEAD`）；
> 实现 `pet/` 63 个文件 +6282 / −944，测试 53 个文件 +7564 / −583，工具 `tools/` 15 个新文件，
> 提示词 `prompts/` 3 个新文件，其余为文档与配置。共 38 个提交（不含本报告这一个）。
> **关联**：协议与数据流见 [`AGENT_LINK_PROTOCOL.md`](AGENT_LINK_PROTOCOL.md) §3.1 / §6；
> 素材链见 [`../tools/asset_pipeline/README.md`](../tools/asset_pipeline/README.md)；
> 潜伏崩溃的背景见 [`QT-LIFECYCLE-FULL-SUITE-STABILIZATION-2026-09.md`](QT-LIFECYCLE-FULL-SUITE-STABILIZATION-2026-09.md)。

**证据口径（先说清楚）**：本分支由多个会话在同一工作区里先后提交。下文的数字分两类——

- **本报告撰写会话实测**：直接给命令与输出；
- **取自提交说明**：标注「（提交 `xxxxxxx` 记录）」，是做那一项的会话当时记下的，**本报告没有复测**。

## 一、核心特性

把桌宠从「跟随 DSH」扩成「跟随 Claude Code」，并补齐多屏、身份与一批日常体验问题。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 每个 Claude Code 会话一只小鱼 | 头顶常驻「标题 · 状态」，干活 / 休息各保持一组动画；会话关闭离场；上限可调（默认 6）。 |
| 2 | 会话详情、跳转、专属右键菜单 | 单击小鱼看详情卡（最近的问题、入口、路径与分支）；跳到 VS Code 里的那个对话 / 把终端窗口调到前台；进程不在了的会话自动离场。 |
| 3 | 灵动岛显示 Claude Code | 卡片可显示会话汇总、「最近的对话」折叠框、今日用量，状态灯换成 API 连接图标；移除在线更新入口。 |
| 4 | Claude 通道（Anthropic Messages API） | AI 对话与识屏；默认模型 `claude-sonnet-5`，思考力度可选。 |
| 5 | 跨屏拖动 | 鱼可以拖到任何一块屏幕；「看看屏幕」只截发起者所在的那块屏。 |
| 6 | 程序身份 BigFish | 任务管理器 / 任务栏显示 BigFish 与鱼的图标（源码运行时生成改名启动器）。 |
| 7 | 气泡与配图 | 字体统一用等线；GIF / 动态 WebP 配图会动；配图 / 台词 / 彩蛋弹窗改洗牌式抽取；气泡里「去聊天窗」后对话同步。 |
| 8 | 素材生成链随仓库提供 | 上游的提示词配方与绿幕 → 透明动画脚本，整理成本仓库可直接跑，新增装角色包一步。 |
| 9 | 其它 | 「护驾」（小肥鱼围到主肥鱼身边）、设置页「保存」、生成的鱼不重叠且默认小一号。 |

**红线 / 不变量**

- 事件文件只存元数据：提问正文不落盘（详情卡里的「最近的问题」是点开时从本机 transcript 现读进内存的）。
- 单屏下 `home_bounds` 恒为 `None`、`cross_screen` 恒为 `False`：事件与边界路径与改动前相同。
- 跳转时窗口没调到前台就不发 VS Code 链接（链接在当前聚焦窗口生效，发错会新开空对话）。
- `tests/test_architecture.py` 的退役层守卫不变；`modern_settings_dialog.py` 的行数预算随「保存」功能校准到 2413（提交 `b298c59` 记录）。

## 二、修改文件说明

逐文件增删见本节末尾的两张全量表（由 `git diff --numstat origin/main..HEAD` 生成）。下面按能力说明
主要文件「改了什么 + 为什么」。

### 会话小鱼与 Claude Code 联动

| 文件 | 改动意图 |
|---|---|
| `pet/claude_hooks.py` | hook 脚本在回合边界追加 `SessionMeta`（项目名、标题、完整工作目录、transcript 路径）；`ClaudeSessionTracker` 另出一路逐会话更新（`working / waiting / resting / gone`），附加字段随更新捎带但不单独触发。 |
| `pet/agent_link.py` | `ClaudeCodeMonitor` 发 `session_update`；每 60 秒按运行清单核对会话进程，进程已不在的按 `SessionEnd` 处理（被杀掉的 Claude Code 不发 `SessionEnd`）。 |
| `pet/overlay_session_pets.py`（新） | 会话 ↔ 临时 sprite：出场 / 标签 / 保持动画 / 离场；「让这只离场」后该会话关闭前不再生小鱼。 |
| `pet/claude_session_info.py`（新） | 按需读 transcript 尾部与 `~/.claude/sessions/<pid>.json`；两处都是内部格式，一律「读不到就留空」；WSL 经一次 `wsl.exe` 取回。 |
| `pet/claude_session_jump.py`（新） | 按窗口标题找 VS Code 窗口、按进程链找终端宿主窗口，逐级加码地调到前台，再发会话链接。 |
| `pet/session_pet_ui.py`（新） | 详情卡、专属右键菜单与动作集（后台线程读取 / 跳转，信号回 GUI 线程）。 |
| `pet/sprite_behavior.py` / `pet/pet_sprite.py` | `BehaviorController.hold`（保持一组动画）；`PetSprite.caption`（常驻标签，渲染一次后贴图）。 |
| `pet/claude_session_history.py` / `pet/session_history_service.py` / `pet/island_history_panel.py`（新） | 「最近的对话」的存储规则、回填扫描与岛上的折叠列表。 |
| `pet/claude_usage.py` / `pet/claude_usage_monitor.py` / `pet/api_key_monitor.py`（新） | 今日用量（增量读 transcript）与 API 连接体检。 |

### Claude 通道

| 文件 | 改动意图 |
|---|---|
| `pet/chat/anthropic_provider.py`（新） | 官方 `anthropic` SDK 流式对话、识图、连接测试；三处入口兜住全部异常（缺凭据时 SDK 抛的是 `TypeError`，会杀掉工作线程）。 |
| `pet/chat/models.py` / `service.py` / `ai_settings_page.py` | `api_format` / `effort` 字段、`RoutingProvider` 路由、设置页的思考力度行。 |
| `pet/vision.py` | 识屏按 `uses_anthropic` 路由；`capture_screen_bytes(rect)` 只截一块显示器并对齐到 Win32 报告的矩形。 |
| `requirements.txt` | 新增 `anthropic>=1.0`（**打包脚本尚未配收集项**，见实机记录的未验证项）。 |

### 跨屏

| 文件 | 改动意图 |
|---|---|
| `pet/overlay_viewport.py`（新） | 副屏视口窗：画主合成窗的同一批 sprite，鼠标事件换算后转交。 |
| `pet/overlay_screens.py`（新） | `ScreenRouter`：sprite 住在哪块屏、拖拽换屏、屏幕拓扑变化时重新安置、视口生灭。 |
| `pet/overlay_window.py` | `update` 同步到视口、`_event_pos`（跨屏时按全局坐标取位置）、逐 sprite DPR。 |
| `pet/sprite_bounds.py`（新）与四个控制器 | 行为 / 抛掷物理 / 边缘探头 / 抛掷彩蛋按 sprite 取边界。 |

### 身份、气泡与配图

| 文件 | 改动意图 |
|---|---|
| `pet/app_identity.py`（新）、`tools/make_launcher.py`（新）、`run.bat` | 应用用户模型 ID 与窗口图标；生成 `BigFish.exe`（改名的解释器副本）——任务管理器的进程名取自 exe 版本资源，运行时改不了。 |
| `pet/ui_fonts.py`（新）、`pet/speech_bubble.py`、`pet/quick_chat.py` | 气泡类文字统一用等线（单族；装没装只看字体文件）。 |
| `pet/animated_image.py`（新）、`pet/speech_bubble.py`、`pet/fun_image_popup.py` | 多帧配图交给 `QMovie` 播放，隐藏即停；换帧只重画不重排。 |
| `pet/shuffle_bag.py`（新）、`pet/window_alerts.py` | 洗牌式抽取与进度落盘（`shuffle-state.json`）。 |
| `pet/quick_chat.py`、`pet/chat/widgets.py`、`pet/chat/legacy_widgets.py` | `sync_from_store`：气泡里聊的内容在聊天窗重新打开 / 开着时同步；生成途中交接不丢回答。 |

### 工具与提示词

`tools/asset_pipeline/`（15 个新文件）与 `prompts/`（3 个新文件）取自 PC2005-cloud/dsh-pet @ `9266219`；
相对上游的改动与许可见该目录 README 与 `THIRD_PARTY_NOTICES.md` §2a（脚本 MIT；提示词等素材禁止商用、须署名）。

### 删除

`pet/updater.py`、`pet/update_settings.py`、`tests/test_updater.py`、`tests/test_update_feature.py`（移除在线更新，提交 `f4bb5f1`）；
`tests/test_dynamic_island_balance_tier_time.py`（岛的余额峰谷信息槽被今日用量取代，提交 `0d9679b`）。

### 未改动

- 打包脚本（`scripts/build_onedir.ps1` 等）与打包版 exe 的名字 / 版本信息。
- `tests/conftest.py`：曾尝试加一个全局 autouse fixture，见「实机运行记录 · 排查记录」，已撤回。

### 全量：实现与工具

| 文件 | 增删 |
|---|---|
| `.gitignore` | +3 / −0 |
| `pet/__init__.py` | +1 / −1 |
| `pet/__main__.py` | +5 / −0 |
| `pet/agent_link.py` | +51 / −0 |
| `pet/animated_image.py` | +44 / −0 |
| `pet/api_key_monitor.py` | +184 / −0 |
| `pet/app.py` | +264 / −70 |
| `pet/app_identity.py` | +86 / −0 |
| `pet/catalog.py` | +16 / −0 |
| `pet/chat/ai_settings_page.py` | +20 / −2 |
| `pet/chat/anthropic_provider.py` | +324 / −0 |
| `pet/chat/legacy_widgets.py` | +34 / −6 |
| `pet/chat/models.py` | +7 / −0 |
| `pet/chat/service.py` | +2 / −2 |
| `pet/chat/settings_dialog.py` | +1 / −1 |
| `pet/chat/widgets.py` | +21 / −0 |
| `pet/claude_hooks.py` | +186 / −2 |
| `pet/claude_session_history.py` | +419 / −0 |
| `pet/claude_session_info.py` | +392 / −0 |
| `pet/claude_session_jump.py` | +344 / −0 |
| `pet/claude_usage.py` | +171 / −0 |
| `pet/claude_usage_monitor.py` | +108 / −0 |
| `pet/config.py` | +40 / −6 |
| `pet/context_menus/icons.py` | +3 / −0 |
| `pet/context_menus/legacy.py` | +2 / −0 |
| `pet/context_menus/registry.py` | +11 / −21 |
| `pet/context_menus/shared.py` | +55 / −1 |
| `pet/dynamic_island.py` | +243 / −122 |
| `pet/fun_image_popup.py` | +26 / −12 |
| `pet/island_chat.py` | +2 / −0 |
| `pet/island_history_panel.py` | +274 / −0 |
| `pet/menu_templates/modern-default-v1.json` | +2 / −3 |
| `pet/modern_settings_dialog.py` | +26 / −25 |
| `pet/overlay_screens.py` | +289 / −0 |
| `pet/overlay_session_pets.py` | +171 / −0 |
| `pet/overlay_shell.py` | +272 / −31 |
| `pet/overlay_spawn_state.py` | +66 / −2 |
| `pet/overlay_viewport.py` | +177 / −0 |
| `pet/overlay_window.py` | +86 / −8 |
| `pet/pet_sprite.py` | +113 / −2 |
| `pet/quick_chat.py` | +90 / −22 |
| `pet/session_history_service.py` | +279 / −0 |
| `pet/session_pet_ui.py` | +546 / −0 |
| `pet/settings_pet_controls.py` | +13 / −11 |
| `pet/settings_save.py` | +61 / −0 |
| `pet/settings_theme_qss.py` | +4 / −10 |
| `pet/settings_widgets.py` | +0 / −1 |
| `pet/shuffle_bag.py` | +182 / −0 |
| `pet/slot_manager.py` | +7 / −1 |
| `pet/speech_bubble.py` | +69 / −12 |
| `pet/sprite_behavior.py` | +56 / −9 |
| `pet/sprite_bounds.py` | +20 / −0 |
| `pet/sprite_collision.py` | +11 / −1 |
| `pet/sprite_edge_probe.py` | +10 / −5 |
| `pet/sprite_menu_facade.py` | +52 / −17 |
| `pet/sprite_physics.py` | +7 / −4 |
| `pet/sprite_rally.py` | +158 / −0 |
| `pet/sprite_throw_egg.py` | +2 / −1 |
| `pet/ui_fonts.py` | +74 / −0 |
| `pet/update_settings.py` | +0 / −223 |
| `pet/updater.py` | +0 / −289 |
| `pet/vision.py` | +75 / −13 |
| `pet/window.py` | +0 / −1 |
| `pet/window_alerts.py` | +28 / −7 |
| `requirements.txt` | +6 / −0 |
| `run.bat` | +7 / −1 |
| `tools/asset_pipeline/README.md` | +78 / −0 |
| `tools/asset_pipeline/_common.py` | +98 / −0 |
| `tools/asset_pipeline/chroma_step02.py` | +224 / −0 |
| `tools/asset_pipeline/encode_thumbs.py` | +118 / −0 |
| `tools/asset_pipeline/fill_nn.py` | +107 / −0 |
| `tools/asset_pipeline/install_step05.py` | +178 / −0 |
| `tools/asset_pipeline/make_mask_black.py` | +67 / −0 |
| `tools/asset_pipeline/normalize_step03.py` | +225 / −0 |
| `tools/asset_pipeline/pr_import_step02.py` | +122 / −0 |
| `tools/asset_pipeline/preview.html` | +298 / −0 |
| `tools/asset_pipeline/preview.py` | +44 / −0 |
| `tools/asset_pipeline/requirements.txt` | +5 / −0 |
| `tools/asset_pipeline/watermark_mask_v5.mkv` | +- / −- |
| `tools/asset_pipeline/watermark_step01.py` | +79 / −0 |
| `tools/make_launcher.py` | +247 / −0 |

### 全量：测试

| 文件 | 增删 |
|---|---|
| `tests/conftest.py` | +45 / −0 |
| `tests/test_agent_link.py` | +6 / −0 |
| `tests/test_animated_images.py` | +173 / −0 |
| `tests/test_anthropic_provider.py` | +567 / −0 |
| `tests/test_api_key_monitor.py` | +221 / −0 |
| `tests/test_app_identity.py` | +147 / −0 |
| `tests/test_architecture.py` | +7 / −1 |
| `tests/test_asset_pipeline.py` | +187 / −0 |
| `tests/test_chat_subsystem.py` | +49 / −0 |
| `tests/test_claude_hooks.py` | +218 / −0 |
| `tests/test_claude_link.py` | +38 / −1 |
| `tests/test_claude_session_history.py` | +367 / −0 |
| `tests/test_claude_usage.py` | +204 / −0 |
| `tests/test_claude_usage_monitor.py` | +128 / −0 |
| `tests/test_config_schema.py` | +1 / −0 |
| `tests/test_desktop_pet_features.py` | +5 / −68 |
| `tests/test_dynamic_island_balance_tier_time.py` | +0 / −107 |
| `tests/test_dynamic_island_revamp.py` | +3 / −3 |
| `tests/test_effects_integration.py` | +0 / −1 |
| `tests/test_first_batch_features.py` | +2 / −41 |
| `tests/test_island_card_text.py` | +232 / −0 |
| `tests/test_island_content_cache.py` | +7 / −34 |
| `tests/test_island_history_panel.py` | +197 / −0 |
| `tests/test_island_info_slot.py` | +191 / −0 |
| `tests/test_island_session_history.py` | +400 / −0 |
| `tests/test_island_shell_wiring.py` | +264 / −0 |
| `tests/test_island_status_indicator.py` | +167 / −0 |
| `tests/test_menu_layout.py` | +7 / −11 |
| `tests/test_overlay_cross_screen.py` | +369 / −0 |
| `tests/test_overlay_rally.py` | +230 / −0 |
| `tests/test_overlay_session_pets.py` | +394 / −0 |
| `tests/test_overlay_spawn_state.py` | +53 / −0 |
| `tests/test_overlay_viewport.py` | +338 / −0 |
| `tests/test_quick_chat_sync.py` | +238 / −0 |
| `tests/test_second_batch.py` | +2 / −2 |
| `tests/test_session_history_service.py` | +292 / −0 |
| `tests/test_session_pet_details.py` | +510 / −0 |
| `tests/test_settings_and_resources.py` | +22 / −0 |
| `tests/test_settings_interaction_tabs.py` | +1 / −1 |
| `tests/test_settings_save_without_exit.py` | +142 / −0 |
| `tests/test_shuffle_bag.py` | +258 / −0 |
| `tests/test_single_process_shared.py` | +3 / −0 |
| `tests/test_slot_and_memory.py` | +34 / −1 |
| `tests/test_sprite_caption.py` | +197 / −0 |
| `tests/test_sprite_collision.py` | +36 / −0 |
| `tests/test_sprite_hold.py` | +95 / −0 |
| `tests/test_sprite_menu_parity.py` | +7 / −6 |
| `tests/test_sprite_menu_target.py` | +11 / −31 |
| `tests/test_sprite_rally.py` | +229 / −0 |
| `tests/test_ui_fonts.py` | +110 / −0 |
| `tests/test_update_entry_removed.py` | +160 / −0 |
| `tests/test_update_feature.py` | +0 / −78 |
| `tests/test_updater.py` | +0 / −197 |

## 三、实现要点

- **会话小鱼的数据流**：hook（同步，POSIX sh，只读 stdin 前 4096 字节）→ 事件文件 → `ClaudeSessionTracker`
  （worker 线程）→ `session_update` 信号 → `SessionPetController`（GUI 线程）。主肥鱼的 Agent 级状态管线不受影响。
- **跨屏用「视口」而不是「sprite 换窗」**：sprite 始终住在主合成窗里，坐标是「全局逻辑坐标 − 合成窗原点」，
  可以落在窗口矩形之外；副屏只多一个画同一批 sprite 的窗。这样位置监听、移除通知、碰撞世界都不用按窗分区，
  不同屏的 sprite 在同一坐标系里天然不相撞。屏与屏的逻辑坐标是分段的，所以跨屏时事件位置必须取全局坐标。
- **改名启动器**：复制基础解释器的 `pythonw.exe`，用 `BeginUpdateResource / UpdateResource` 换掉图标与版本资源，
  连同核心 DLL 放进 `.venv\Scripts`。旁边上一级有 `pyvenv.cfg`，照样按这个虚拟环境找包，而且从
  「启动器 + 解释器」两个进程变成一个。只改副本；改过资源后原签名失效（不影响运行）。
- **内部格式一律降级**：transcript 条目格式官方文档明说会变，`~/.claude/sessions` 没有文档。所有读取都按
  「读不到就留空」写，存活判定在清单没有记录时返回「不知道」而不是「死了」。

## 四、性能分析

环境：Windows 11，20 核，三屏 125% 缩放 / 144Hz，Python 3.13.15，PySide6 / Qt 6.11。

| 路径 | 数字 | 触发频率 | 来源 |
|---|---|---|---|
| 每只会话小鱼的稳态开销 | 约 9% 单核、3～4MB | 常驻（每只） | 本会话实测（py-spy + 进程计数器） |
| hook 额外开销（回合边界读 transcript 尾部） | Git Bash +55ms、WSL +5ms（3MB transcript） | 每回合 2 次 | 本会话实测 |
| 会话详情读取 | 本机 1～15ms；WSL 约 120ms（一次 `wsl.exe`） | 点开详情 / 跳转时 | 本会话实测（4 个本机 + 6 个 WSL 真实会话） |
| 会话存活核对 | 同上量级，在监视器 worker 线程 | 每 60 秒，且有会话时 | 本会话实测 |
| `OverlayWindow.update` 多一层转发 | 无视口 143 → 315ns；有视口且脏区不在其上 2.3µs | 每次重绘请求 | 本会话实测（`timeit`，20 万次 × 5 取最小） |
| 洗牌出牌并落盘 | 0.69ms / 次，状态文件约 2KB | 每次自言自语 / 开弹窗 | 本会话实测（35 张图 + 5 句台词，600 次平均） |
| 动图配图 | 300×428、122 帧、7.5MB 的 GIF：3 秒换 24 帧，进程 CPU 读数约 0，RSS +8MB | 气泡显示动图期间 | 本会话实测 |
| 气泡字体换等线 | 「中文 + 英文」+1MB（与微软雅黑 UI 相同）；缺字形时两者同样一次性 +51MB；默认 Segoe UI 画第一句中文即 +51MB | 首次渲染 | 本会话实测（逐句量 RSS） |
| 「护驾」落点计算 | 6 只 0.46ms / 24 只 2.39ms；没有鱼在飞时每 tick +48ns | 点一次算一次 | 提交 `b12e901` 记录 |
| 「最近的对话」回填 | 16 个会话 84ms | 展开卡片时（服务内节流） | 提交 `56da3d9` / `31ef3c8` 记录 |
| 今日用量 | 首次 36MB / 108ms，之后每次约 2ms | 周期刷新 | 提交 `0d9679b` 记录 |

逐条回答：

- **稳态开销**：没有 Claude Code 会话、没有副屏视口时，新增的只有 `update` 的一层转发（+约 170ns / 次）。
- **新的系统调用 / 线程 / 磁盘**：会话存活核对读 `~/.claude/sessions/*.json`（WSL 通道起一次 `wsl.exe`，带
  `CREATE_NO_WINDOW`）；洗牌每出一张原子写一次约 2KB 的文件；详情与跳转各起一个短命后台线程。
- **新的网络**：只有用户选了 Claude 通道时的 Anthropic API 请求。会话小鱼、详情、跳转、今日用量全部是本地数据。
- **内存**：每只会话小鱼 3～4MB；每块有鱼住的副屏多一个整屏透明窗（没有鱼住时自动关掉）。

## 五、实机运行记录

本机真实环境（非 CI、非 mock），2026-10-10 ～ 10-11。

**全量测试**（`.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`，`QT_QPA_PLATFORM=offscreen`）：

```text
5 failed, 4858 passed, 14 skipped, 244 warnings in 400.53s (0:06:40)
```

5 个失败均与本分支无关：4 个是本机既有的环境性基线（路径超 260、子进程输出按 cp1252 解码 ×2、多显示器负原点），
另一个 `test_catalog_animation_count_guard_survives_optimize` 是同文件里时过时不过的子进程编码用例（单跑通过）。

**跨屏拖动**：真实鼠标输入（`SetCursorPos` + `mouse_event`）把一只鱼 主屏 → G3223Q → S2721DGF → 主屏，
逐步核对归属、落点、截图里的像素与视口开关：

```text
released on DELL G3223Q: screen=DELL G3223Q pos=(4545,452) bounds=(3840, -995, 1728, 3072) viewports=['DELL G3223Q']
  ok   fish is painted on DELL G3223Q (1.00 of its rect is blue)
released on Dell AW3821DW: screen=Dell AW3821DW pos=(1377,527) bounds=(0, 0, 3072, 1232) viewports=[]
RESULT: PASS
```

**识屏截取范围**：`native_rect` 与 `EnumDisplayMonitors` 三屏逐一相等；单屏截图 768 像素长边（原先整个虚拟桌面
缩成 768×396，每块屏只剩 150～400 像素宽）。

**Claude 通道**：用真实 Key（只经进程环境变量，未落盘）跑通连接测试 1.8s、流式对话、识图读出测试数字、
识屏完整路径；`claude-sonnet-5` 思考力度 medium 首字 2.5s / low 0.8s。

**会话详情与跳转**：本机 4 个 + WSL 6 个真实会话的详情读取与存活判定全部正确，窗口匹配全部命中；
连续跳转 4 个本机会话（VS Code 插件 ×2、Windows Terminal、VS Code 内置终端），前台窗口均切到目标：

```text
9099ca93 VS Code 插件 | True 已跳到 VS Code 里的这个对话 | foreground now: (1118360, 'dsh-pet-indesktop - …')
d3134df6 终端 | True 已切到终端窗口（具体标签页要自己选） | foreground now: (8393470, 'Ubuntu-24.04')
```

**BigFish 身份**：重启后进程为单个 `BigFish.exe`（`FileDescription = BigFish`）；用它开的窗口在任务栏上是鱼的图标、
独立成组（截图确认）。

**素材链**：合成绿幕视频跑通五步，产物 `vp9, 640x360, 24 fps`，透明区 alpha ≤ 8、角色处 255，角色中心 x=320、脚底 y=329，
装好的角色包被 `pet.catalog` 识别。

**未验证 / 无法自动验证的项（如实登记）**

| 项 | 为什么没验证 |
|---|---|
| VS Code 链接发出后目标会话的标签页是否被切到前面 | 从进程外看不到 VS Code 内部的标签页；窗口标题在 4 秒内未变化，可能是 VS Code 首次收到外部链接的确认弹窗在等用户。按插件 2.1.283 的代码，已打开的会话是 `reveal` 它的面板。需用户点一次确认。 |
| WSL 会话的实际跳转 | 窗口匹配已对上，没有真的切过去。 |
| 混合缩放下的跨屏 | 本机三屏都是 125%。 |
| `anthropic` 依赖的打包 | 三个构建脚本尚未为它配收集项，打包版不保证 Claude 通道可用。 |
| 素材链在真实 AI 生成视频上的抠像质量 | 只用合成绿幕视频跑过。 |
| 灵动岛、会话历史、今日用量、护驾、设置页保存、移除在线更新 | 由另外的会话完成，其验证见各自提交说明；本报告未复测。 |
| 重启后桌宠里的肉眼观感（详情卡、动图气泡、等线字体） | 只做了离屏 / 单独渲染截图，没有人眼在运行中的桌宠上确认。 |

**排查记录（供后来者）**：洗牌改动的第一版往 `tests/conftest.py` 加了一个全局 autouse fixture，全量在
`tests/test_recovery_hints.py::test_enabling_mouse_through_shows_recovery_hint` 的 `app.processEvents()` 上稳定
`Windows fatal exception: access violation`（单跑不崩，只跑前半或后半的测试文件也不崩）。逐项排除（关掉动图播放、
把洗牌换回独立随机、固定弹窗选图、不接状态文件）都照样崩；把 fixture 体换成只有一个 `yield` 仍然崩，去掉 fixture
就不崩。结论：与产品代码无关，是新增的全局 fixture 改变了整套用例的对象回收时机，引出一个潜伏的 Qt 生命周期崩溃。
已改为只在该测试文件内隔离；**潜伏的崩溃本身没有修**。

## 六、已知限制

- 抛出去的鱼不跨屏（在本屏边缘反弹）；全屏避让 / 隐藏仍按整体；拖文件投喂只在主屏生效。
- 跳转只支持 Windows；终端会话只能把窗口调到前台，选不了标签页；VS Code 内置终端里的会话若工作目录不是任何窗口的
  工作区，只能猜一个最近用过的窗口。
- 灵动岛卡片里的会话列表还不能点击跳转。
- 屏幕身份用 `QScreen.name()`（本机是型号名），两块同型号的屏会认成第一块。
- 打包版的 exe 名字与版本信息未改；`BigFish.exe` 只在源码运行时生成。
