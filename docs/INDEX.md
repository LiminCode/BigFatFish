# 文档索引

本文件是 `docs/` 与仓库根级文档的**唯一入口索引**。目的是按 Wikipedia 式的方式组织知识：每个文档一行，写明「它是什么」和「什么时候该读它」，读者可以顺着索引直接跳到相关条目，不必通读整个目录才知道功能模块在哪里。

怎么用：

1. **不知道从哪开始** → 先读根级入口表，再按领域找到对应分组。
2. **要改某块代码但不确定影响面** → 直接在本文搜索关键词（如 `ffmpeg`、`菜单`、`设置`、`ggml`），命中的行的「何时必读」就是判断依据。
3. **「何时必读」优先沿用 `AGENTS.md` 的 "Context pointers" 口径**（那是最权威的现行约定）；该节没有覆盖的文档，按文档正文自身标注的用途如实概括。

## 新文档入场规则

本节是规则的**出处**；任何新增文档都必须遵守：

1. **任何新文档必须在本文登记一行**，否则视为未定义的孤儿文档（审查时应作为缺陷提出）。
2. **新文档必须与相关文档互链**：正文中至少一处指向它所补充或取代的既有文档（用仓库相对路径），并同步更新本索引中那些文档行的「何时必读」。
3. **取代旧文档时**，先在被取代文档的「何时必读」里写明谁取代了它，再考虑是否删除；在删除前不得让两个文档同时作为权威描述存在。
4. **有明确生效范围的文档，标题或首段必须写清基线**（分支 / 版本 / 日期 / 实测用例数）；只描述"当时的快照"的文档必须自带「历史快照」警示（写法参见上游的 [`OPTIMIZATION_CHECKLIST.md`（上游）](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/OPTIMIZATION_CHECKLIST.md)、[`HANDOVER_2026-09.md`（上游）](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/HANDOVER_2026-09.md)，链接在 [`UPSTREAM.md`](UPSTREAM.md)）。
5. **「何时必读」写触发条件，不写文档摘要**：写成"改 X 之前必读"，不要写成"介绍了 X"。

---

## 根级入口

| 文档 | 一句话内容 | 何时必读 |
|---|---|---|
| [`../README.md`](../README.md) / [`../README.zh-CN.md`](../README.zh-CN.md) | 项目主页（英文 / 中文，内容一致）：是什么、截图、快速开始、功能清单、已知限制、隐私、与上游的关系。 | 第一次接触项目；查用户可见行为。**改了用户看得见的功能，两份一起改**。 |
| [`UPSTREAM.md`](UPSTREAM.md) | 2026-11-02 移出本仓库的上游文档清单（发版、打包、DSH、插件化路线、上游 PR 报告等），每条链到上游 `ee699c7` 的固定版本。 | 追溯 fork 之前某个机制的来历、或代码注释里出现指向上游的链接时；新文档不要再链到这些文档的本地路径。 |
| [`../AGENTS.md`](../AGENTS.md) | 工程指南：项目结构、变更纪律、CI 成本纪律、"Context pointers" 触发表、agent skills 入口。 | 提交任何代码之前；尤其改动 ffmpeg 派生、菜单、设置、PR 合并前，先查 "Context pointers"。 |
| [`../CONTEXT.md`](../CONTEXT.md) | 领域术语表（Shared UX Contract / Settings System / Menu Action Model / Report Gate / Session-End Spawn Freeze 等）与禁用说法。 | 命名新概念、写设计文档、或需要确认"这个词在本项目里到底指什么"时；提案与既有术语冲突时必须先读。 |
| [`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) | 第三方素材与组件的授权声明。 | 新增/替换动画素材、图标、字体或第三方库时。 |
| [`../prompts/README.md`](../prompts/README.md) | AI 生成素材用的提示词配方（动作视频的通用前缀 + 一百多个动作的按秒分解、成套通知图标）的用法、换角色时怎么改、来源与许可（上游素材禁止商用、须署名）。 | 做新动作 / 新角色、改提示词文件、或要引用 / 再分发这些配方之前。下一步见 [`../tools/asset_pipeline/README.md`](../tools/asset_pipeline/README.md)。 |
| [`../tools/asset_pipeline/README.md`](../tools/asset_pipeline/README.md) | 素材生成链：绿幕源视频 → 水印填充 → 抠像 → 归一化 → 640×360 透明 webm → 装成角色包（含 `body_box` 测量）的五步用法、工作目录约定、相对上游的改动清单。 | **改 `tools/asset_pipeline/` 任一脚本、角色包规格（画布 / `FEET_Y` / `body_box` 口径）、或要从零做一套角色素材时必读**；提示词见 [`../prompts/README.md`](../prompts/README.md)，授权见 `THIRD_PARTY_NOTICES.md` §2a。 |

---

## 渲染、解码与窗口结构

| 文档 | 一句话内容 | 何时必读 |
|---|---|---|
| [`WINDOW_PY_SPLIT_GUIDE.md`](WINDOW_PY_SPLIT_GUIDE.md) | `pet/window.py`（`PetWindow`）的演进指南：功能驱动的拆分流程、控制器边界与架构红线。 | **给 `window.py` 加功能前必读**（README 口径）；凡新功能预计超过约 100 行、或需改 3 个以上同域方法、或行数预算告警时，先按本文拆控制器。现行行数预算的实测值与「为什么这次只能校准而不是拆分」见 [`PR-REPORT-ISSUE-186-TRAY-MENU-2026-09-23.md`（上游）](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-ISSUE-186-TRAY-MENU-2026-09-23.md)。 |
| [`QT-LIFECYCLE-FULL-SUITE-STABILIZATION-2026-09.md`](QT-LIFECYCLE-FULL-SUITE-STABILIZATION-2026-09.md) | Qt 生命周期与全量套件稳定性收口记录：Windows/offscreen 下原生崩溃（0xC0000005 / 0xC0000374）的归属分析与 QObject owner 清理方案。 | 全量套件出现随机原生崩溃、或改动 `PetWindow.closeEvent()`、`PetSpeechBubble` owner 清理、菜单执行 seam、后台资源 teardown 时。 |

> 与 ffmpeg 派生、预热调度、Windows 关机/注销路径相关的权威档案是 issue #111（见下方「专项 issue 档案与事故复盘」分组），因为改这几处代码同时牵涉渲染生命周期与会话拆除时序。

---

## 交互、菜单与设置

| 文档 | 一句话内容 | 何时必读 |
|---|---|---|
| [`CONTEXT-MENU-RESEARCH-AND-REFACTOR-2026-08-25.md`](CONTEXT-MENU-RESEARCH-AND-REFACTOR-2026-08-25.md) | 右键菜单图标调研与双模板（`modern-default-v1`）重构记录，含菜单布局树的顺序/显隐/别名/图标覆盖规则与 2026-09 生命周期收口补充。 | **改右键菜单结构、样式、交互或平台行为时必读**（AGENTS.md 口径）。**删除已有菜单项**（入口收敛）时还要看 [`PR-REPORT-ISSUE-186-TRAY-MENU-2026-09-23.md`（上游）](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-ISSUE-186-TRAY-MENU-2026-09-23.md)：模板/注册表/legacy 三处怎么改，以及用户旧 `context_menu_layout` 里的残留节点怎么清。 |
| [`SETTINGS-CHANGE-GATES.md`](SETTINGS-CHANGE-GATES.md) | Settings System 的变更门禁：一条设置能否进入设置页的准入条件、以及变更的准出证据要求。 | **新增、移动、重命名、删除或改变任何持久设置、以及修改设置页布局/保存语义/平台可见性/依赖关系之前必读**（AGENTS.md 口径）。 |

---

## 聊天、语音与内容功能

| 文档 | 一句话内容 | 何时必读 |
|---|---|---|
| [`ISSUE-EDGE-TTS-VOICE-DEPRECATION-2026-09-22.md`](ISSUE-EDGE-TTS-VOICE-DEPRECATION-2026-09-22.md) | 事故档案：edge 合成「没声音」的两条根因（微软下架音色 + 连发偶发空音频）与对策（音色表兜底、重试、非空缓存判定）。 | **改语音报时的合成/缓存路径、或再遇到「配置了却没声音」时必读**；它记录了 `NoAudioReceived` 为什么不等于网络问题的判断链。 |

---

## Agent 联动与 DSH

| 文档 | 一句话内容 | 何时必读 |
|---|---|---|
| [`AGENT_LINK_PROTOCOL.md`](AGENT_LINK_PROTOCOL.md) | 多 Agent 联动统一事件协议与扩展指南：本地文件事件总线、六态词汇、第三方 Agent 接入与新增内置 Agent 的步骤。 | 接入新 Agent、改事件归一（`normalize_event_state`）或六态词汇时；面向集成方的对外协议口径以本文为准。 |

---

## 台词、人格与预设数据

| 文档 | 一句话内容 | 何时必读 |
|---|---|---|
| [`PERSONA-PHRASES-PRESET-STORAGE-2026-09-08.md`](PERSONA-PHRASES-PRESET-STORAGE-2026-09-08.md) | 台词预设的存储与加载架构：内置预设（数据文件）/ 用户台词（config）/ 便携模板（运行时生成）三类内容的归属与路由。 | **改台词预设文件 `pet/persona_presets/*.json`、短语加载 `persona_phrases.py`、或表达风格语义（`dialogue_mode` / `dialogue_phrases`）之前必读**（AGENTS.md 口径）。 |
| [`PERSONA-TEMPLATE-FIELD-ALIGNMENT-2026-09-05.md`](PERSONA-TEMPLATE-FIELD-ALIGNMENT-2026-09-05.md) | 台词模板变量名契约：代码 kwargs ↔ 模板 `{占位符}` 的逐 key 对照表（由 `pet/persona_template.py` 常量自动生成）。 | 新增/重命名模板变量、或改事件可用变量集合时；必须先改代码常量再重新生成本文，否则 `test_persona_template.py` 的 AST 双向校验会红。 |

---

## 专项 issue 档案与事故复盘

| 文档 | 一句话内容 | 何时必读 |
|---|---|---|
| [`ISSUE-111-WINDOWS-SESSION-END-FFMPEG-2026-09-12.md`](ISSUE-111-WINDOWS-SESSION-END-FFMPEG-2026-09-12.md) | issue #111 专项档案：Windows 关机/注销弹 `0xc0000142` 的根因（会话拆除期派生进程）与「会话结束冻结」闸门设计。 | **改 ffmpeg 派生（`webm_clip` 的 reader / 首帧 / meta / exe 探测）、预热调度、或任何在 Windows 关机/注销时运行的东西（`session_watcher`、`match_shutdown`、`AppShell._on_session_end`）时必读**（AGENTS.md 口径）。 |
| [`PR-MERGE-LESSONS-2026-09-12.md`](PR-MERGE-LESSONS-2026-09-12.md) | PR 合并三则教训：叠放 PR 在 squash 父 PR 后必然冲突、预算/红线只在两 PR 组合时才破、时序测试 flake 纪律。 | **合并 PR 之前必读**（AGENTS.md 口径）。 |
| [`NETWORK-PROXY-AND-VPN-2026-09-22.md`](NETWORK-PROXY-AND-VPN-2026-09-22.md) | 代理/VPN 影响面清单：歌词取词（代理下 20~41s 超时）、edge-tts 语音、更新检查（jsdelivr 只有代理能通）、余额/识屏/对话（用户自配端点）、localhost 类（本地 TTS / DSH 联动）各自该不该走代理，附 30 秒探针与推荐分流配置。 | **改任何联网功能，或用户报「某功能昨天还好好的 / 歌词没了 / 语音不出声 / 更新检查失败」时必读**（系统代理与 VPN 是一等嫌疑）；也用于回答"桌宠为什么不自己绕过代理"。 |

> 注：`docs/ISSUE-42-POSIX-COLLISION-IPC-2026-08-31.md`（碰撞选举 / QLocal IPC / 协调者锁）从未入库，
> `AGENTS.md` 曾经指向它的那条 Context pointer 已随 Phase 4.4b 退役（碰撞 IPC / 协调者文件锁
> 整体删除）一并移除——该课题不再存在待读文档。

---

## PR 报告存档

| 文档 | 一句话内容 | 何时必读 |
|---|---|---|
| [`PR-REPORT-SESSION-WORKSPACE-MEMORY-2026-11-08.md`](PR-REPORT-SESSION-WORKSPACE-MEMORY-2026-11-08.md) | 「跳到对话」记住会话当时的 VS Code 工作区：「最近的对话」多一个 `workspace`（工作区文件 / 文件夹、名字、**文件夹列表**），活着时由详情卡与历史服务（每会话 10 分钟一次）记下；冻结鱼重开 / 列表点一行先认记录——开着就只在那个窗口里找，关了就按记录开回来（未命名工作区文件没了就把文件夹一起开），**不再借**别的恰好也包含这个目录的工作区；没记录的老会话从 VS Code 关掉的窗口状态库里找回（`workspace_from_storage`）；冻结会话的卡片不再按目录猜；未命名的 WSL 远程工作区（`Code/Workspaces/<id>/workspace.json` + `remoteAuthority`）能被认出。含实机根因探针与耗时。 | 改冻结鱼 / 「最近的对话」在 VS Code 里重开的路径、改 `HistoryEntry` 字段、或看到「跳到对话跳错了工作区 / 新开了窗口」之前必读；活着的会话怎么找窗口见 `tests/test_session_jump_workspaces.py` 模块说明。 |
| [`PR-REPORT-TOAST-CLICK-FORGOTTEN-2026-11-03.md`](PR-REPORT-TOAST-CLICK-FORGOTTEN-2026-11-03.md) | 自家弹窗里最底下的旧通知点了没反应的两个原因：服务名单只留最近 `keep` 条、卡片却一直留着，点击拿 uid 去查名单查不到就被静默丢掉（修：卡片带 `Notice` 本体直接跳，名单未命中记日志、岛上给提示）；Chrome 自己已撤掉的网页通知再派点击是空操作（未修，记了判定办法与可选退路）。含 Chrome 通知库 WAL 的解析结论、三次重放的窗口观测。 | 看到「通知点了没反应」先读这里；改 `NotificationService.activate` 的入参、弹窗点击链路、或想给 Chrome 已撤通知做退路之前必读。 |
| [`PR-REPORT-FISH-LINEUP-SPACING-2026-11-06.md`](PR-REPORT-FISH-LINEUP-SPACING-2026-11-06.md) | 「列队」按「身体框 ∪ 头顶标签胶囊」的占位框留间距：`lineup_spots` 新关键字 `halos`（每只一项相对身体框的占位框），左右间距、换排高度、让障碍都按占位框算，返回的仍是身体框左上角，不传时行为不变；`lineup_pets` 用 `caption_rect()` 算占位框。真机 20 只（15 活 + 5 冻结）两排、标签全部完整可见。 | 改「列队」的落点间距 / 换排、或想让「护驾」也照顾标签之前必读；列队本体（排序、飞行）见 `PR-REPORT-FISH-LINEUP-2026-11-02.md`。 |
| [`PR-REPORT-ISLAND-CARD-FITS-SCREEN-2026-11-06.md`](PR-REPORT-ISLAND-CARD-FITS-SCREEN-2026-11-06.md) | 灵动岛展开的卡片整块放进所在屏幕的工作区：卡片（胶囊 44 + 内容）总高按 `availableGeometry()` 算上限，放不下先压「消息记录」/「最近的对话」的可见行数（`_fit_card_to_screen`：行高算术、从更高的框一行一行拿、各自最少 2 行、多出的滚动），预算与配置的行数分开存（`set_row_budget` vs `set_max_visible`）换屏即恢复；卡片在胶囊下方时夹屏按工作区不盖任务栏（`_clamp_bounds`），胶囊态仍按整块物理屏。第二轮（11-07）：岛靠屏幕下半部分时卡片开在胶囊**上方**、胶囊原地不动（`_prefers_card_above` 比两个方向夹屏后的位移，`_capsule_top` 把胶囊画到窗口底部），几何动画进行中 `_update_size` 只改终点不再整块闪现。含修前 / 修后假屏复现与真机探针矩形。 | 改岛卡片的高度 / 两个折叠框露几行 / 展开方向与夹屏边界 / 胶囊在窗口里的位置（命中、绘制），或想让卡片整块滚动之前必读；胶囊为什么能盖任务栏见 `PR-REPORT-ISLAND-OVER-TASKBAR-2026-11-05.md`。 |
| [`PR-REPORT-ISLAND-COLLAPSE-RETURNS-2026-11-06.md`](PR-REPORT-ISLAND-COLLAPSE-RETURNS-2026-11-06.md) | 灵动岛收起卡片回到展开前的位置：卡片（实机 1182 px）比屏幕剩余高度高时展开被 `_clamp_rect` 顶到顶边，此前收起按当前左上角放胶囊、就留在顶边（用户报「岛不见了」）。现在 `expand_card` 记下胶囊左上角 `_rest_anchor`，`collapse_card` 回到它（仍夹屏），`_finish_animations` 先落到动画终点再重算。含修前 / 修后真机探针矩形记录。 | 改岛的展开 / 收起 / 动画收尾、或想给卡片高度加上限之前必读；展开瞬间 x 左移的未解之谜记在第七节。 |
| [`PR-REPORT-ISLAND-MESSAGE-LOG-2026-11-06.md`](PR-REPORT-ISLAND-MESSAGE-LOG-2026-11-06.md) | 灵动岛卡片里的「通知」框换成「消息记录」：大肥鱼冒过的通知气泡（联动的开始 / 完成 / 需要批准 / 失败、Slack 总结提醒、隐藏期改道到岛的反馈）都记进 `pet/message_log.py`（`message-log.json`，留 200 条，看没看过跨重启），每条写明是哪个 Claude Code 会话（标题 / 从哪开的 / 目录，和会话小鱼卡片同一份），铃铛 = 没看过的条数，点一行切到那个对话。来源靠联动气泡带的 `origin`（通道 + 最近一条记录的会话）；过程汇报气泡不记。Windows 通知中心只喂自家弹窗，读取 + 弹窗都开着才轮询。 | 改 `message_log.py` / `island_message_panel.py`、岛上铃铛与消息框的接线（`AppShell._record_message` 等）、给气泡加来源、或想把别的气泡也记进来 / 排除掉之前必读；想知道「这条通知是哪个对话的」怎么判定时看这里。 |
| [`PR-REPORT-ISLAND-OVER-TASKBAR-2026-11-05.md`](PR-REPORT-ISLAND-OVER-TASKBAR-2026-11-05.md) | 灵动岛可以盖在任务栏正上方：三处「夹回屏幕」（`_clamp_rect` / `_clamp_to_screen` / 拖拽松手）从工作区改成整块物理屏（`_placement_bounds`），停靠判定仍按工作区。含真机对照探针（原生把岛挪进任务栏：旧版 5 s 内推回、新版 40 s 不动）。 | 改岛的位置夹取、默认落点，或想限制岛能摆在哪之前必读；任务栏那一侧为什么不停靠见 `PR-REPORT-ISLAND-DOCK-TASKBAR-2026-11-05.md`。 |
| [`PR-REPORT-ISLAND-USAGE-TILE-POLISH-2026-11-05.md`](PR-REPORT-ISLAND-USAGE-TILE-POLISH-2026-11-05.md) | 灵动岛用量磁贴的一组打磨：倾斜角按磁贴长边反比限幅（`metro_tilt_params`，宽磁贴不再乱晃）、信息槽去掉「今日」、两个账号的「Win / WSL」换成 Windows 四格窗 / Ubuntu 一环三点记号（监视器多发一份分段）；近 7 天仪表盘窗口底色透明、磁贴底下加阴影、页头文字带反色光晕；岛可见期间 2 s 一轮置顶看门狗，只在被别的进程的窗真盖住时重插（`platform_win.occluder_above`，自家的通知卡片 / 仪表盘不算）。含外来置顶窗盖上去 1.76 s 回来的实机探针。 | 改岛上 Metro 磁贴的倾斜手感、用量文案 / 记号、仪表盘外观，或岛 / 通知卡片的置顶策略之前必读。 |
| [`PR-REPORT-ISLAND-DOCK-TASKBAR-2026-11-05.md`](PR-REPORT-ISLAND-DOCK-TASKBAR-2026-11-05.md) | 灵动岛「靠边半隐藏」不再把任务栏上沿当屏幕边缘：停靠判定只认工作区边与物理屏边重合的那几边（`dockable_edges`，工作区向内缩进 ≥ 8px 的边视为被任务栏 / 系统面板占住），岛贴着任务栏松手就以完整胶囊停在它上面；启动 / 刷新配置时存着的停靠边落在被占的边上按 `none` 复位落盘；松手日志带「可停靠」边。含三屏工作区缩进探针与改动前的 `dock=bottom` 日志现场。 | 改灵动岛停靠判定 / 细条位置 / 夹屏几何、任务栏或多屏相关的岛行为，或想给被占的边加停靠开关之前必读。 |
| [`PR-REPORT-ISLAND-USAGE-TWO-ACCOUNTS-2026-11-02.md`](PR-REPORT-ISLAND-USAGE-TWO-ACCOUNTS-2026-11-02.md) | 灵动岛「今日用量」与近 7 天仪表盘把 Windows 账号和 WSL 发行版里的账号分开各显各的（`今日 Win 2.41M · WSL 1.80M`、磁贴每天并排两根柱）：`UsageMeter` / `WeekMeter` 支持多个 projects 根，`UsageAccounts` / `WeekAccounts` 经 `\\wsl.localhost\<发行版>\home\<用户>\.claude\projects` 读、只碰在运行的发行版、读不到显示 `--` 并保留当天已读到的数；目录枚举改 `os.scandir`（UNC 上一遍 2.7 s → 1.1 s）。含 UNC 的实测耗时与一次性坑（共享刚起来时 `WinError 3`、`root` 家目录拒绝访问）。 | 改今日用量 / 周用量的统计口径、根的发现、岛信息槽文案、仪表盘用量 / 消息磁贴的分账号画法，或想再读 WSL 里别的 `~/.claude` 文件之前必读。 |
| [`PR-REPORT-SESSION-FISH-ADOPTED-REAP-2026-11-02.md`](PR-REPORT-SESSION-FISH-ADOPTED-REAP-2026-11-02.md) | 会话小鱼认领路径的漏洞修复：从运行清单认领来的会话进程退出后清单文件被删、hook 又不报 SessionEnd，鱼永远「工作中」（实机：肥鱼自己的 Slack 关注 `claude -p` 变成一条停不下来的 SDK 小鱼）。追踪器记「清单里见过」、连着两轮查不到就按已关闭收；`wsl_liveness` 失败抛出而不是全 None；WSL 清单脚本按进程环境里的 `BIG_FAT_FISH_HEADLESS` 标出肥鱼自己的无界面运行（`@@headless`），认领时跳过。含用假清单记录 + `sleep` 进程做的真机探针。 | 改认领 / 存活核对 / 退场规则、`WSL_SCRIPT` 的输出格式、或给肥鱼加新的无界面 `claude -p` 运行之前必读。 |
| [`PR-REPORT-FISH-LINEUP-2026-11-02.md`](PR-REPORT-FISH-LINEUP-2026-11-02.md) | 主肥鱼右键菜单「列队」（紧跟「护驾」）：所有小肥鱼到主屏底边从左到右站成一排，按状态分组（等你批准 / 等你回复 → 工作中 → 休息中 → 冻结 → 手动生的），同档最近更新的在前；一排站满往上再排、让过主肥鱼和灵动岛；飞行段复用护驾（固定锚）。 | 改「护驾 / 列队」的落点算法、飞行段、主肥鱼菜单的交互段条目之前必读。 |
| [`PR-REPORT-SESSION-FISH-PERSIST-2026-11-02.md`](PR-REPORT-SESSION-FISH-PERSIST-2026-11-02.md) | 会话小鱼「一直在」：重启后从 Claude Code 的运行中会话清单（`~/.claude/sessions`）认领开着的会话（含 WSL），按 idle / busy / waiting 给姿势；最近 X 天开过、进程已不在的对话变成冻结的鱼（灰标签、停住不动；菜单可恢复：桌面版深链 / 终端 `claude --resume`）；用户「关闭这只」落盘跨重启，会话再活跃即作废，离开名册即忘；新设置 `session_fish_keep_days`（右键菜单里）。含「为什么重启后空闲的鱼会消失」的机制调查和第一次实机启动失败（壳构造期间生鱼）的教训。 | 改会话小鱼的生灭 / 认领 / 冻结 / 关闭语义、运行清单解析、历史行字段，或给冻结状态加素材之前必读；认领来的会话怎么退场、无界面运行为什么不认领，见 `PR-REPORT-SESSION-FISH-ADOPTED-REAP-2026-11-02.md`。 |
| [`PR-REPORT-FISH-HOST-BADGE-2026-11-02.md`](PR-REPORT-FISH-HOST-BADGE-2026-11-02.md) | 小肥鱼标签胶囊最左边加「从哪开的」图标（来源 → 桂冠 → 名字 · 状态）：与详情卡页头同一份 `host_icons`（VS Code / Claude 桌面版 / PowerShell / WSL 企鹅的真图标，没装就单色记号、颜色跟胶囊字色）；判定同 `host_kind`，冻结鱼按历史行的入口；`host_icon` 多 `ink`、`host_icon_for_dpr`。 | 改标签胶囊的排版 / 缓存、来源图标的取图与缓存、会话小鱼标签下发之前必读。 |
| [`PR-REPORT-TOAST-TOPMOST-2026-11-02.md`](PR-REPORT-TOAST-TOPMOST-2026-11-02.md) | 通知卡片「中间空一块」的排查与修复：卡片窗口在、位置对、内容画了，却在 z 序里掉到一个最大化的 Electron 窗口（Windows 当它全屏）之下；从不激活的置顶窗被盖住就不会自己回来。每次重排 + 在场期间每 2 s 的看门狗把卡按老 → 新重新 `SetWindowPos(HWND_TOPMOST)`，真全屏时不插；顺手修展开的一摞用收起高度摆位导致下面那张叠上去。附完整的排查路径（离屏 / 真实窗口复现、渲染回放、GDI 计数、z 序链、`WindowFromPoint`）。 | 通知弹窗「看不见 / 缺一块 / 被盖住」、或任何从不激活的置顶窗口（灵动岛、气泡）又出现「盖住了就不回来」时必读；改 `ToastStack._reflow` / 看门狗周期之前必读。 |
| [`PR-REPORT-MEMORY-DISTILL-PHASE1-2026-10-31.md`](PR-REPORT-MEMORY-DISTILL-PHASE1-2026-10-31.md) | 会话记忆蒸馏·第一期：从 Claude Code 自己落盘的会话记录（`~/.claude/projects`）增量抽「我说过的话」（剥系统注入、丢噪音、带 Claude 上一条正文、AskUserQuestion 的回答算决定、按词打规则 / 决定 / 纠正 / 任务标签），按 cwd 分个人 / 公司侧（桌面版的 WSL 会话也在 Windows 的 `projects/ssh-*/` 里，入口分不出来），存进本地不进 git 的候选库（按天一文件、滚动 90 天）；独立 Metro 流程页（六格流程图实时数字、每个 Claude 环境的记忆库入口、候选列表、统计、当前设置）；设置页一节含明文提示词。蒸馏 / 审核 / 落盘是第二期。 | 改 `memory_distill*.py`、候选库格式、分流规则、流程页，或开始做第二期（蒸馏 / 审核 / 落盘）之前必读。 |
| [`PR-REPORT-SESSION-CARD-METRO-2026-10-28.md`](PR-REPORT-SESSION-CARD-METRO-2026-10-28.md) | 会话小鱼详情卡改成 Metro 风格（方角平铺、强调色页头、页头用来源程序自己的图标、模型 / 思考强度 / 持续缩成一行灰色小字、目录和分支放一块磁贴里可左右滑可复制、倾斜方按钮），文字大小单独一项（85–130%）；加上下文用量（最近一轮主对话 usage，压缩后用 `postTokens`，窗口按模型查）和 VS Code 插件会话所在的工作区（与跳转同一套线索）。字体只点一个族（雅黑 UI / 细体 / 等宽）；每个配色方案加 `accent`；共用图标库加 `ink` 参数与 folder / branch / jump；`host_icons` 认得商店版 Claude 桌面版。 | 改详情卡布局 / 配色方案、会话记录解析、上下文窗口表，或往共用图标库加名字之前必读。 |
| [`PR-REPORT-SESSION-FISH-JUMP-2026-10-28.md`](PR-REPORT-SESSION-FISH-JUMP-2026-10-28.md) | 点会话小鱼直接切到那个对话：Claude 桌面版会话用运行清单的 `hostSessionId` 打开 `claude://claude.ai/epitaxy/<id>`；Windows Terminal 会话调到前台后用 UI 自动化按会话标题选中标签页（`pick_tab`）。 | 改 `claude_session_jump.py` 的跳转路径、运行清单字段，或想支持别的终端的标签页之前必读。 |
| [`PR-REPORT-NOTIFICATION-TOASTS-2026-10-28.md`](PR-REPORT-NOTIFICATION-TOASTS-2026-10-28.md) | 自家 Metro 通知弹窗：新通知几条同时叠在选定的角 / 屏（Windows 横幅一次只一条），Slack 按频道、Chrome 按网站叠成一摞，点开展开、点哪条跳哪条；启动参数从通知库副本里查，Slack 协议链接 / Chrome `--notification-launch-id` 直接跳，不开通知中心；全屏、开着勿扰（WNF `QUIETHOURS` 状态，`platform_win.quiet_hours_profile`）时不弹。新一级设置域「通知」。 | 改通知读取 / 弹窗 / 跳转、`notification_toast.py`、勿扰判断，或想把别的应用也归组之前必读。 |
| [`PR-REPORT-UPSTREAM-SYNC-2026-10-24.md`](PR-REPORT-UPSTREAM-SYNC-2026-10-24.md) | 对上游 v4.3.0→v4.4.0 的挑拣同步（merge 有 130 个文件冲突，只 cherry-pick / 手工移植）：agent-link 定时器泄漏、待办两条、设置窗打开提速（5366→855 ms，无父行闪顶层窗）、聊天窗七步（底部空白 / Markdown / 粘贴图 / 时间感知 / 关闭即销毁 RSS −23 MB / Esc 收尾 / 岛会话退出不覆盖）、帧序列 v3→v6（白底残留、无损、3 条预取线程；运行时迁移配额每启动 1 个 clip，全量重出走 CLI）。写明有意不搬的那一串和为什么；时间感知为了提示缓存改了落点。 | 再看上游要拿什么、改聊天窗生命周期 / Markdown / 提示词时间信息、或再动帧序列档位串之前必读。 |
| [`PR-REPORT-SETTINGS-FOCUS-2026-10-21.md`](PR-REPORT-SETTINGS-FOCUS-2026-10-21.md) | 设置窗口开着时再点「肥鱼设置」：按 `settings.lock` 的持锁 pid 找到那扇窗，用会话跳转的 `focus_window` 调到前台（真机探针：锁 pid → 「肥鱼设置」窗 → 前台）；调不上来才弹原来的「已经打开」通知。`pet/settings_focus.py`。 | 改设置进程单实例 / 锁文件 / 「已经打开」提示，或想把别的子进程窗口拿到前台之前必读。 |
| [`PR-REPORT-VOICE-CHIME-QUOTES-2026-10-21.md`](PR-REPORT-VOICE-CHIME-QUOTES-2026-10-21.md) | 语音报时的内置台词库（中 120 / 英 96 条）在设置页「语音 → 台词 / 歌词」里看得见、改得了（预填、「恢复内置」；没改过存空串以跟上代码更新，改过整份存 `voice_chime_builtin_quotes_zh/_en`）；自定义台词改成**追加**在内置库后面一起轮换（以前是整体替换）。`quote_pool(cfg)` 是唯一取库的入口。 | 改报时台词的来源 / 轮换、`voice_chime_quotes.py`、或想把别的内置文案库做成可编辑之前必读。 |
| [`PR-REPORT-SLACK-NOTES-2026-10-20.md`](PR-REPORT-SLACK-NOTES-2026-10-20.md) | Slack 关注每条「需要你看的」存成 AI-Base-Memory `slack/` 下一条 Markdown（和笔记同格式、同一条 git 通道、按链接去重），简报窗口第三页「Slack 关注」最新最前：查看（开链接）/ 稍后 ▾ / 完成；稍后到点由笔记那套提醒再冒气泡「查看 / 稍后 1 小时 / 完成」；总提醒多「稍后 1 小时」。`WorkNotesService(folder=, label=)` 泛化、进程级 git 锁。 | 改 Slack 关注的存档 / 「Slack 关注」页、`WorkNotesService` 的目录参数、`SYNC_PATHS`，或想把别的东西也存进那个仓库之前必读。 |
| [`PR-REPORT-NOTE-META-BAR-2026-10-20.md`](PR-REPORT-NOTE-META-BAR-2026-10-20.md) | 笔记详情里的基本信息（记下的时间、模型、tokens、花费、用时）从正文挪到详情底部一条不随正文滚动的信息栏：每项一个自画线条图标（时钟 / 火花 / 进出箭头 / 美元硬币 / 秒表），数字缩写、精确值在悬停里，跟白天 / 黑夜换色；「笔记」与「Slack 关注」两页都有。 | 改笔记详情的排版、用量字段的显示、或简报窗口色板之前必读。 |
| [`PR-REPORT-ISLAND-ICON-PICKER-2026-10-20.md`](PR-REPORT-ISLAND-ICON-PICKER-2026-10-20.md) | 设置页「桌面组件 · 图标」从头像 / emoji 下拉框改成图标方块：点一下直接弹系统选文件，选中的图缩到 128 存成 PNG 复制进配置目录 `island-icons/`（原文件删了也不影响），「用鱼本体头像」回默认，保存时清旧副本；配置仍是 `img:<路径>`。 | 改灵动岛图标的设置入口、`img:` 图标的存放位置、或想恢复 emoji 选项之前必读。 |
| [`PR-REPORT-HISTORY-PIN-2026-10-20.md`](PR-REPORT-HISTORY-PIN-2026-10-20.md) | 灵动岛「最近的对话」加置顶：右键「置顶 / 取消置顶」，置顶的行一直排最前、不过期、不被条数上限挤掉，标题右边一枚主题色图钉；`HistoryEntry.pinned` 随历史文件落盘（旧文件无此键 = 没置顶）。 | 改「最近的对话」的排序 / 清理规则、右键菜单、或历史文件格式之前必读。 |
| [`PR-REPORT-LANGUAGE-RELOAD-2026-10-20.md`](PR-REPORT-LANGUAGE-RELOAD-2026-10-20.md) | 设置里切语言后运行中的肥鱼没真正切：`Config.reload()` 在合并磁盘值之前就 `set_language` 了旧值，直到重启都按旧语言出简报 / 笔记；改取 `raw` 的值；两套提示词的语言要求改成无条件（即使原文是英文）。 | 改 `Config.reload()`、界面语言的生效路径、或提示词的语言要求之前必读。 |
| [`PR-REPORT-NOTES-PUSH-STATUS-2026-10-19.md`](PR-REPORT-NOTES-PUSH-STATUS-2026-10-19.md) | 工作笔记推不上去的真相：WSL 里公司的 git 钩子（Sphinx 理解检查）要在终端答问卷，无界面推送被拒、本地攒提交；`describe_sync_failure` 认出钩子给专门说明，状态行带 tooltip，笔记页加「再推一次」；笔记服务的状态文案走 `t()`。 | 看到「git 没推上去」或改笔记的 git 推送之前必读。 |
| [`PR-REPORT-BRIEFING-LANGUAGE-SOURCES-2026-10-19.md`](PR-REPORT-BRIEFING-LANGUAGE-SOURCES-2026-10-19.md) | 工作简报 / 工作笔记按界面语言整套切换提示词（英文版 `Summary:` + 英文小节；解析两种概要前缀）；简报来源可配置 `work_briefing.sources`（jira / pr / slack / calendar / email / suggestions，邮件默认关）——开关同时决定提示词、输出小节、放行的只读工具、要不要跑 gh；新设置节「工作简报」+「这个功能怎么运作」（什么时候 / 发给 Claude 什么 / 它能用什么 / 结果放哪 / 不会做什么）。实测英文简报 88.8 s、0 个中文字符。 | 改简报 / 笔记的提示词、来源、放行工具，或加新来源之前必读。 |
| [`PR-REPORT-PERSONA-PRESETS-ENGLISH-2026-10-19.md`](PR-REPORT-PERSONA-PRESETS-ENGLISH-2026-10-19.md) | 内置表达风格的英文版：`persona_presets/<mode>.en.json` 两份（30 事件 × 3 条，占位符对齐）；`builtin_phrases(mode, language=None)` 按界面语言按键覆盖、缺键回退中文；Agent 气泡、设置页预览、「改成我的台词」三处跟语言；事件词表仍由中文文件定义。 | 改内置台词、再加一种语言、或改 `builtin_phrases` 的回退之前必读。 |
| [`PR-REPORT-REST-ENGLISH-2026-10-19.md`](PR-REPORT-REST-ENGLISH-2026-10-19.md) | 其余界面英文化（第三轮）：聊天窗（新版 / 旧版 / 旧版聊天内设置 / 裁切）、快速对话、拖文件解读、喂食 / 看屏幕气泡、待办、会话跳转、两条模型通道与知识库同步的错误文案：333 个键；有意不翻的是给模型的提示词、内置台词与角色台词、兜底托盘、动画名；被当判断依据的「认证失败」关键词不能翻。附整个 `pet/` 的中文字面量盘点。 | 新增任何聊天窗 / 气泡 / 错误文案之前必读；想让 Agent 联动气泡也说英文（内置预设是中文内容）之前必读「后续」。 |
| [`PR-REPORT-DIALOGUE-PREVIEW-2026-10-18.md`](PR-REPORT-DIALOGUE-PREVIEW-2026-10-18.md) | 内置表达风格不再是黑箱：选「默认 / 鲸鱼娘」时逐事件编辑框只读地显示那套台词、折叠框改名；「改成我的台词」把整套复制进自定义台词并切到自定义模式（已有内容先确认）；预览期间保存 / 切层 / 导出不写回缓冲；导出模板带当前显示的台词。运行时路由与内置 JSON 不动。 | 改设置页台词编辑区、导入 / 导出模板、或想让某个只读预设变成可编辑之前必读。 |
| [`PR-REPORT-PERSONA-SETTINGS-HINTS-2026-10-18.md`](PR-REPORT-PERSONA-SETTINGS-HINTS-2026-10-18.md) | 肥鱼「性格」设定的全盘点（对话人设 vs 气泡台词模板 vs 其他固定文字 vs 不走人设的 AI 任务：各存在哪、怎么起作用、影响什么、经不经模型）；设置页据此改：人设 / 关于我自成「人设与回复」一节并加说明节，「表达风格」等 8 条提示改成说真话（它不管自言自语 / 主动识屏、留空回退到代码兜底），台词模板也加说明节；通用 `settings_help.help_row / help_section`。 | 改人设拼法、台词预设路由、或任何涉及「肥鱼怎么说话」的设置文案之前必读。 |
| [`PR-REPORT-PERSONAL-ASSISTANT-2026-10-17.md`](PR-REPORT-PERSONAL-ASSISTANT-2026-10-17.md) | 个人助理：灵动岛人形图标 → 自己的窗口；个人简报由肥鱼自己的 Claude（个人 key、Anthropic 直连、`anthropic_provider.complete` 无头工具循环）只读地读本地 AI-Base 克隆，顶部写明模型 / 思考强度 / token / 秒 / 工具轮 / 读过的文件；灵感记录追加到 `User/灵感 Inspiration.md` 后用 Windows git + 钥匙串 Token 推送（被拒退到 GCM 一次）；在 Obsidian 打开用 `path=`。设置里模型与强度可单独选。实测一次简报 85～90 秒、输入 20～26 万 token。 | 改个人助理任何一环、想让肥鱼的个人 key 做别的无头任务（复用 `complete`）、或在 Windows 侧跑 git 之前必读。 |
| [`PR-REPORT-WORK-NOTES-LAYOUT-2026-10-16.md`](PR-REPORT-WORK-NOTES-LAYOUT-2026-10-16.md) | 工作笔记页：列表 / 详情从上下改成左右（可拖 `QSplitter`，列表行两行、关横向滚动条）；总结提示词多要一个 `title`，`apply_summary` 用它换掉「Slack 消息」这类泛称标题，文件名不变。2 张截图在 `docs/screenshots/work-notes-layout-2026-10-16/`。 | 改笔记页布局、列表行文案、或总结回答的字段之前必读。 |
| [`PR-REPORT-MENU-CORNERS-2026-10-16.md`](PR-REPORT-MENU-CORNERS-2026-10-16.md) | 右键菜单圆角四角发黑的根因与修法：Windows 只给「带 alpha 且 Frameless」或「不透明度 < 1」的窗口分层样式，`QMenu` 是 `Popup` 没有 Frameless 位，于是只在淡入动画里逐像素透明、淡入一结束被摘掉分层 → 黑角；新版样式给菜单与子菜单加 `FramelessWindowHint`（黑像素 196 → 0）；系统 `CS_DROPSHADOW` 阴影是直角的，关掉后在 10px 透明边距里自己画跟圆角走的软阴影（PySide 6.12 `setWindowFlag(NoDropShadowWindowHint)` 不生效，要 `setWindowFlags`）。顺手让旧编排里的「桌宠控制」也跟界面语言。 | 改右键菜单的透明 / 圆角 / 阴影 / 窗口标志，或任何「某个顶层弹窗圆角外发黑」的问题之前必读。 |
| [`PR-REPORT-MENU-ENGLISH-2026-10-16.md`](PR-REPORT-MENU-ENGLISH-2026-10-16.md) | 右键菜单英文化（新版 / 旧版模板全部子菜单与置灰提示、会话小鱼菜单与详情卡、托盘菜单）：212 个 `menu.*` 键；动作名 / 图标选项 / 开关标签 / 置灰原因等导入时求值的表显示时翻译；模板自带子菜单名在用户编排里也按「仍是原文才翻」处理；按文字找锚点的两处钉到同一个键。英文界面下菜单里的中文从 72 / 64 条降到 1 / 0（剩彩蛋标题，属配置内容）。 | 新增或改名任何右键菜单项、托盘菜单项、会话小鱼菜单项之前必读；写「按菜单文字找某一项」的逻辑之前必读。 |
| [`PR-REPORT-SETTINGS-ENGLISH-2026-10-16.md`](PR-REPORT-SETTINGS-ENGLISH-2026-10-16.md) | 设置窗口英文化：AST 抽取 17 个设置模块的中文字面量（~660 条运行时 + 93 条导入时求值），人工译成英文，脚本改写成 `t("settings.…")`，797 个键；侧栏域名 / 事件名表保持中文作内部标识、显示时翻译；别的模块的下拉选项（报时频率、音色、气泡方案……）按 id 取键。英文界面下可见中文从 686 条降到 13 条有意保留的。含 9 张英文截图与「按钮被定宽截断」的修复。 | 新增或修改任何设置项文案之前必读（文案要直接写成 t() 并在两张表各加一条）；想继续翻右键菜单 / 托盘 / 聊天窗之前看这里的抽取与改写脚本思路。 |
| [`PR-REPORT-WORK-NOTES-SETTINGS-2026-10-15.md`](PR-REPORT-WORK-NOTES-SETTINGS-2026-10-15.md) | 工作笔记进设置页（「自动化与联动」一节：悬停讲完整流程的图标、开关、仓库目录、模型）；每条笔记记下总结用的模型 / token / 费用 / 秒数（来自 claude -p 结果的 modelUsage）；「记下」按钮与输入框同高。4 张设置页截图在 `docs/screenshots/work-notes-settings-2026-10-15/`。 | 改工作笔记的设置、用量字段、或想给别的设置节加「流程解释图标」之前必读。 |
| [`PR-REPORT-BRIEFING-METRO-2026-10-15.md`](PR-REPORT-BRIEFING-METRO-2026-10-15.md) | 工作简报窗口（含 Slack 关注、「笔记」页）改 Windows Phone / Metro：复用设置页的 `METRO_TOKENS`，pivot 页头、平铺磁贴、倾斜描边按钮；白天 / 黑夜跟随「外观」主题、右上角当场切换并写回；简报 / Slack 关注文案 27 个键进语言表。8 张 light/dark × zh/en 渲染截图在 `docs/screenshots/briefing-metro-2026-10-15/`。 | 改简报 / Slack 关注 / 笔记窗口的样式、主题或文案之前必读；想给别的窗口套 Metro 之前看这里怎么复用令牌。 |
| [`PR-REPORT-WORK-NOTES-2026-10-15.md`](PR-REPORT-WORK-NOTES-2026-10-15.md) | 工作笔记：简报窗口新「笔记」页，随手记 Slack / Jira 链接或片段（原文逐字保留），落盘后 WSL 里的公司 Claude Code 只读地读链接、写摘要、定下次提醒（本机 9.7 秒一条），到点冒留到点为止的气泡；笔记是 Obsidian 风格 Markdown，存在公司私有仓库 AI-Base-Memory 的 `note/`（副本放 Windows，git 经 WSL 在 /mnt/c 里跑，3.5 秒一次）。含 Obsidian 不认 UNC / 映射盘 / `open?path=` 新建库的三次实测、论坛共识与改放 NTFS 的决定。 | 改工作笔记 / 简报窗口标签页 / `work_notes` 配置键之前必读；想让肥鱼与 Obsidian 库打交道、或往 AI-Base-Memory 仓库里写别的东西（公司 AI 记忆）之前必读。 |
| [`PR-REPORT-CLAUDE-LAUNCHERS-2026-10-15.md`](PR-REPORT-CLAUDE-LAUNCHERS-2026-10-15.md) | 右键菜单两条入口「Claude Desktop」「Claude Code（WSL）」：商店版 Claude 经 `shell:AppsFolder\<家族名>!Claude` 拉起（家族名从注册表包仓库解析，本机 182 个包 0.4 ms），WSL 那条照「在终端继续」的命令在家目录起新会话；没装置灰。新模块 `pet/claude_launchers.py` 零 Qt、无配置键、无线程。含真实环境一次拉起的进程记录与两个查找函数的实测耗时。 | 改右键菜单里的外部程序入口、想让肥鱼拉起 / 对接 Claude Desktop 或 WSL 里的 Claude Code 之前必读；想做「肥鱼转发对话给 Claude Code」之前必读——先看这里为什么只做了拉起。 |
| [`PR-REPORT-YOUTUBE-MUSIC-2026-10-15.md`](PR-REPORT-YOUTUBE-MUSIC-2026-10-15.md) | 右键菜单「YouTube Music」（默认浏览器打开首页，不自动播放）；网易云 / QQ 音乐整块下线：找程序的 `music_players.py`、每次启动在几个盘符里的后台扫描（本机实测 3.4～4.6 秒）、设置页三行、配置键 `music_player_paths`（加载时丢弃）、「打开并播放」的启动代码。歌词与唱歌联动照旧（读系统媒体会话；查词仍用 QQ 音乐 / lrclib / 网易云的公开接口）。含真实 Qt 平台下点击打开 Chrome 的记录、用户菜单编排自动补入新项的解析结果，以及「没在运行中的肥鱼上点过、没放歌验证歌词」的登记。 | 改右键菜单里的音乐 / 外部网站入口、`now_playing` 的会话控制、设置页「音乐关联」组之前必读；想重新接入本地播放器（网易云 / QQ 音乐 / Spotify 客户端）之前必读——先看这里删了什么、为什么。 |
| [`PR-REPORT-RENAME-FISH-2026-10-14.md`](PR-REPORT-RENAME-FISH-2026-10-14.md) | 界面里不再叫「桌宠」，改叫「肥鱼」：`pet/` 与 `tests/` 里的 .py / .json / .sh 整词替换（186 个文件、833 处，含注释与断言），`docs/`、README、`.agents/` 不动；设置页侧栏左下角的版本号去掉（不再发版）。 | 给界面写中文文案时必读（主体叫「肥鱼」，不叫桌宠 / 桌面助手）；想换别的名字时照这里的脚本再跑一遍；校订 README 时从这里接着做。 |
| [`PR-REPORT-REMOVE-DEEPSEEK-ENTRIES-2026-10-14.md`](PR-REPORT-REMOVE-DEEPSEEK-ENTRIES-2026-10-14.md) | DeepSeek 的入口全部下线：右键「DeepSeek 余额 / DeepSeek Harness 子菜单 / 打开网页版 DeepSeek」、托盘同名三项、「Agent 联动」里的 DSH 开关、设置页「随桌宠启动 dsh 服务 / 自启目标 / 点击显示余额」、灵动岛「卡片内容」的余额项；三个 action id 进 `_MENU_LAYOUT_DROPPED_ACTIONS`，老布局加载时清掉。余额查询、Harness 启动器、DSH 监视器与配置键都保留。 | 想把 `pet/balance.py`、`pet/harness_launcher.py`、`DshMonitor` 整个删掉时必读（这里记了哪些还在被谁用）；用户问「启动 dsh / 余额去哪了」时必读。 |
| [`PR-REPORT-REMOVE-DEEPSEEK-SETTINGS-2026-10-14.md`](PR-REPORT-REMOVE-DEEPSEEK-SETTINGS-2026-10-14.md) | 设置页里的 DeepSeek 痕迹下线：「AI 与对话 → 余额与服务状态」整节（余额自动刷新、峰谷文案 / 文本 / 颜色）摘掉，配置键与余额代码保留；「卡片内容」「每日请求上限」说明去品牌；对话窗口风格「肥鱼版 DeepSeek」改名「肥鱼版宽屏」（配置值不变）。右键菜单与 DSH 的 DeepSeek 条目没动。 | 想把余额 / 峰谷功能整个删掉、或要动右键菜单里剩下的 DeepSeek 条目时必读（这里记了哪些留着、为什么）；用户问「峰谷文案设置去哪了」时必读。 |
| [`PR-REPORT-SETTINGS-METRO-2026-10-14.md`](PR-REPORT-SETTINGS-METRO-2026-10-14.md) | 设置页改成 Windows Phone / Metro 风格：全部方角、卡片是没有描边的平铺磁贴、页标题大而轻、侧栏选中 = 主题色满宽条、按钮 2px 描边；页内的左右分段标签（菜单 / 互动）改成上下折叠的手风琴（`SettingsTabContainer` 同名同 API）；可点的磁贴（按钮、折叠表头、侧栏项）朝光标倾斜（`tilt_transform` / `TiltButton` / `TiltItemDelegate`）；开关改成方角的 Metro 样式；令牌集中在 `settings_theme_qss.METRO_TOKENS`。 | 改设置页任何样式、令牌、`SettingsTabContainer`、`SettingsDisclosureHeader`、`ToggleSwitch`、倾斜效果之前必读；`.agents/skills/desktop-pet-ui-style/references/visual-system.md` 已同步，加控件时按那份写；用户反馈「某处还是圆角 / 倾斜方向反了 / 折叠页切不过去」时必读。 |
| [`PR-REPORT-SLACK-WATCH-2026-10-14.md`](PR-REPORT-SLACK-WATCH-2026-10-14.md) | Slack 关注：电脑在用（没锁屏、最近 10 分钟动过键鼠）时每 15 分钟让 WSL 里的 Claude Code 经 Slack 连接器只读地看一眼「有没有需要我回复 / 处理的」，返回约定的 JSON；只对上次没提醒过的条目冒带按钮的提醒气泡（查看 / 知道了），全文复用简报的窗口；右键「Agent 联动 → Slack 关注」开关、间隔、现在检查。和工作简报同一条通道、同一套只读红线。 | 改 `pet/slack_watch*.py`、`session_active`（锁屏 / 闲置判定）、提示词的 JSON 约定、`fresh_items` 的去重之前必读；想把别的「定时让那个账号看一眼」接进来时照这个做；用户反馈「老是重复提醒 / 锁屏了还在跑 / 没提醒」时必读。 |
| [`PR-REPORT-NOTIFICATION-CENTER-2026-10-14.md`](PR-REPORT-NOTIFICATION-CENTER-2026-10-14.md) | 灵动岛上的通知中心：Windows 通知中心里的 Slack 通知（WinRT `UserNotificationListener`，3 秒一轮、上一轮按 id 复用）铺成卡片里的「通知」折叠框，胶囊上简报右边多一个铃铛；点一条 = 打开通知中心、UI 自动化找到那条并 Invoke，Windows 把激活交给 Slack 跳到那条消息（按频道名的 `slack://channel` 深链接不认名字还会弄坏 Slack，本地缓存里也找不到频道 id——四条路的实测都在报告里）；通知中心里没有了就退回 `slack://open?team=`。配置 `notifications`，设置页「自动化与联动 → 通知中心」。 | 改 `pet/notification_center.py`（读 / 合并 / UIA 激活）、`notification_service.py`、`island_notification_panel.py`、岛上按钮排版（`_toolbar_left` / `_button_rect`）之前必读；想接别的应用的通知、或用户反馈「点了没跳 / 跳到别的频道 / 铃铛不出现」时必读；Windows 升级后通知中心的 UIA 结构（`MainListView` / `ListViewItem`）变了先核对这里。 |
| [`PR-REPORT-SESSION-CROWN-2026-10-14.md`](PR-REPORT-SESSION-CROWN-2026-10-14.md) | 会话小鱼头顶胶囊左侧的金色桂冠，给跑着指定模型的会话戴：hook 脚本在回合边界从记录尾部多取 `model`，随会话更新捎带；`agent_link.crown_models` 是匹配片段清单（默认 `["fable"]`），右键「Agent 联动 → 桂冠给哪个模型」多选（四个家族 + 在场型号），勾完当场换。 | 改 hook 脚本的 SessionMeta、`_EXTRA_KEYS`、`set_session_pet_caption` 的 badge、`_paint_crown`、`session_crown.py` 之前必读；想给别的模型 / 状态加记号时从这里接着做。 |
| [`PR-REPORT-SESSION-CARD-MODEL-EFFORT-2026-10-14.md`](PR-REPORT-SESSION-CARD-MODEL-EFFORT-2026-10-14.md) | 会话小鱼详情卡的状态行显示在用的模型与 effort（「休息中 · Fable 5.1 · high · 已 5 小时」）：从会话记录的 `assistant` 记录读 `message.model` / `requestedModel` / `perTurnEffort` / `effort`，子代理记录跳过；`model_label` 把 id 变成可读名。 | 改 `parse_transcript_tail`、`SessionDetail` 字段、`status_line`、详情卡合并字段的那张名单之前必读；Claude Code 升级后模型 / effort 显示不出来时先核对这里记的字段名。 |
| [`PR-REPORT-UI-LANGUAGE-ISLAND-2026-10-14.md`](PR-REPORT-UI-LANGUAGE-ISLAND-2026-10-14.md) | 界面语言（中文 / English）第一片：`pet/i18n.py` 查表层（英文标识符做键，`pet/locale/zh.json` / `en.json` 两张表，缺英文退中文），配置项 `ui_language`，设置页「常规」第一节「语言 / Language」；覆盖灵动岛胶囊与展开卡片（会话计数、卡片标题、最近的对话、时间与来源、动作结果、API 与余额说明）。中文模式逐字不变；运行中切换靠配置重载 + app 重推。 | 给任何界面文字加英文之前必读（键名规范、单复数写法、两条守卫测试、怎么让运行中的控件跟着换）；改 `PHASE_TEXT`、`ago_text`、`where`、岛卡片文案之前必读；下一片（小鱼详情卡、右键菜单、设置页）从这里接着做。 |
| [`PR-REPORT-ISLAND-HISTORY-TILES-2026-10-14.md`](PR-REPORT-ISLAND-HISTORY-TILES-2026-10-14.md) | 灵动岛「最近的对话」改成 Windows Phone 式的平铺卡片：表头与每行都是方角卡片，行首按来源带单色图标（VS Code / 本机终端 / WSL 终端 / 脚本，`HistoryEntry.host`），进行中的行左缘一道主题色竖条，卡片底色随岛的深浅配色。行高 36 → 40。第二轮：图标改用本机程序自己的（`host_icons.py`：Code.exe / PowerShell / wsl.exe，经外壳取图，启动后预热），没有就退回手绘记号。 | 改 `island_history_panel.py` 的样式、`HistoryEntry.host`、岛卡片里列表的行数据之前必读；想把岛卡片其余部分也改成这个风格时必读（这里记了取了哪些、没取哪些）。 |
| [`PR-REPORT-VSCODE-WORKSPACES-MENU-2026-10-13.md`](PR-REPORT-VSCODE-WORKSPACES-MENU-2026-10-13.md) | 右键菜单「VS Code 工作区」：列出开着的（VS Code 窗口清单）、最近用过的（`workspaceStorage/<id>/state.vscdb` 的修改时间——这个版本的 VS Code 已不存「最近打开」列表）、用户目录里的 `*.code-workspace`；点一条聚焦或 `code` 打开；同名加父目录区分；设置页「自动化与联动」新一节（目录 + 条数）。同一提交把「音乐」从右键菜单下线（只摘入口，歌词与唱歌保留）。第二轮：条目带 Ubuntu / Windows 简化图标、开着的加绿点；「显示本轮消费」（DeepSeek 余额差）从菜单与设置页下线，配置键与结算代码保留。第三轮：设置页按本机装的 WSL 发行版分行填目录（默认发行版标出），菜单顺序改为开着的 → 用户目录里的 → 最近的。 | 改 `pet/vscode_workspaces.py`、`settings_vscode.py`、`add_vscode_workspaces_menu`、`_MENU_LAYOUT_DROPPED_SUBMENUS` 之前必读；想把音乐功能整个删掉时必读（这里记了哪些留着、为什么）；用户反馈「菜单里的工作区不对 / 点了没反应 / 同名分不清」时必读。 |
| [`PR-REPORT-SESSION-JUMP-WORKSPACE-2026-10-12.md`](PR-REPORT-SESSION-JUMP-WORKSPACE-2026-10-12.md) | 「跳到对话」在多文件夹工作区里不再新开 VS Code 窗口：承载会话的窗口标题是 `<工作区名> (Workspace)`，里面没有会话所在文件夹的名字，原逻辑按文件夹名找不到窗口就用 `code` 打开那个文件夹，于是新开一个。改为先问 VS Code 自己——每个窗口的状态库（`workspaceStorage/<id>/state.vscdb`）记着会话是谁的标签页，`storage.json` 记着每个窗口开的文件夹 / 工作区文件——再按标签页标题、启动目录兜底；分不清时让 `code` 按确切目标聚焦。含用户真实桌面上的根因现场与一次真实跳转。 | 改 `pet/claude_session_jump.py`（`opened_workspaces` / `session_windows` / `owning_workspaces` / `vscode_candidates` / `_jump_vscode`）或 `apply_registry` 里的 `start_cwd` 之前必读；用户反馈「跳到对话跳错窗口 / 新开了窗口 / 开了个空对话」时必读；VS Code 升级后跳转变差，先核对这里记的两处内部格式（`storage.json` 的 `windowsState`、状态库里的两个键）有没有变。 |
| [`PR-REPORT-WORK-BRIEFING-2026-10-12.md`](PR-REPORT-WORK-BRIEFING-2026-10-12.md) | 工作简报：桌宠聊天用的 API key 和 WSL 里 Claude Code 登录的账号不是同一个，后者挂着 Slack / Jira / 日历连接器。桌宠每个工作日在 WSL 里无界面跑一次 `claude -p`，由那个账号自己读、自己总结，桌宠只拿结果：一句话概要冒在带按钮的气泡里，全文在一个窗口里。只放行读取类工具、内置工具整个关掉、写入类点名拒绝；PR 由桌宠自己用 `gh` 查（Claude Code 的沙箱连不上 GitHub）；这次运行不冒会话小鱼。含真实账号上的端到端记录。第二轮：工单 / PR / Slack 消息 / 日程都带链接（模型写 + 代码补，不编），灵动岛胶囊最右边多一个打开简报的按钮。 | 改 `pet/work_briefing*.py`、放行 / 拒绝的工具名单、`claude -p` 那一行命令、hook 脚本里的 `BIG_FAT_FISH_HEADLESS` 判断、`linkify` 的补链规则、灵动岛上的简报按钮（`set_briefing_state`）之前必读；想让桌宠读另一个账号的东西（追问简报、接更多来源）时必读——先看「简报内容不离开那条通道」这条线；用户反馈「简报某一节读不到」时，先核对这里记的连接器工具名有没有变。 |
| [`PR-REPORT-SESSION-FISH-AWAITING-REPLY-2026-10-12.md`](PR-REPORT-SESSION-FISH-AWAITING-REPLY-2026-10-12.md) | 会话小鱼的「等你回复」：回合结束后小鱼不再直接进「休息中」，而是停在天蓝标签的「等你回复」，直到用户点「跳到对话」或在那个对话里接着提问——同时开着多个对话时分得出哪些做完了还没看。`review` 是呈现层（`SessionPetController`）在收敛器的 `resting` 上按「看过没有」派生的阶段，收敛器与 hook 不变；灵动岛计数多一项蓝字「待回复」。含逐会话更新路径改动前后的实测、用真实 hook 脚本驱动探针会话的日志，以及「没有在真实桌面上看到变蓝、没有真的点过跳转」的登记。 | 改 `SessionPetController` 的阶段判定（`_presented_phase` / `acknowledge`）、`claude_hooks` 的阶段文案表、会话小鱼标签配色（`PetSprite._CAPTION_TONES`）、灵动岛会话计数配色之前必读；用户反馈「小鱼一直是等你回复 / 做完了没提醒 / 分不清哪些看过」时必读；想给会话加新状态时照此判断该放收敛器还是呈现层。 |
| [`PR-REPORT-SESSION-FISH-RENAME-2026-10-12.md`](PR-REPORT-SESSION-FISH-RENAME-2026-10-12.md) | 会话小鱼的名字跟着用户改的名字走：Claude Code 把自动标题（会话记录里的 `ai-title`）和用户改的名字（`custom-title`，以及运行清单里 `nameSource: user` 的 `name`）分开记，而且改名之后自动标题照样继续追加，所以「取最后一个标题」永远拿不到改的名字。hook 脚本与详情读取都改为「有改的名字就用它」；点开详情卡时顺手更正小鱼头顶的名字。含在一个真实改过名的 WSL 会话上的比对记录。 | 改 `claude_hooks` 里取会话标题的那段 sh、`parse_transcript_tail` / `apply_registry` / `apply_transcript`、`SessionPetController.retitle` 之前必读；用户反馈「小鱼的名字不对 / 改名后没变」时必读；Claude Code 升级后会话名字又不对时，先核对这里记的两种记录格式有没有变。 |
| [`PR-REPORT-BUBBLE-IMAGE-NATURAL-SIZE-2026-10-12.md`](PR-REPORT-BUBBLE-IMAGE-NATURAL-SIZE-2026-10-12.md) | 气泡配图按原始大小显示：此前不论原图多大都被缩放（小图还会放大）进固定的框，标准气泡 220×140、吐气水泡 150×122。改为原始大小 × 「配图大小」比例，长边超过新设置「配图尺寸上限」（160～800，默认 420）才等比缩小；吐气水泡样式下上限约束整个水泡。含两个实测结论：吐气水泡的图片安全区是画布宽的 55%（不是原代码假设的 65%）；解码缓存要按「实际画到的尺寸」留，否则 72 张图从 23 MB 涨到 77 MB。另外运行期间新放进配图目录的图片现在会自动进池。 | 改 `PetSpeechBubble.show_image` / `_breath_size_for_content`、`natural_image_size`、配图缓存的目标尺寸（`self_talk_image_cache_edge_for_limit`）、配图清单的复查之前必读；用户反馈「配图太小 / 太大 / 发糊 / 新加的图不出现 / 内存涨了」时必读。 |
| [`PR-REPORT-EDGE-TTS-ENDPOINT-2026-10-12.md`](PR-REPORT-EDGE-TTS-ENDPOINT-2026-10-12.md) | 整点报时「语音合成失败」：微软关了 edge-tts 用的旧合成端点（握手一律 403，音色列表仍正常；上游 rany2/edge-tts#490，edge-tts 7.2.8 已是最新仍未修）。逐条排除了代理、时钟、版本、调用方式、音色下架。改法是握手被拒（401 / 403）时把端点换成 `api.msedgeservices.com` 再试，默认端点可用时不触发。含连续 4 个整点失败的日志、脱开桌宠的复现、修复后 4 次真实合成的记录，以及「没等到整点实听」的登记。 | 语音报时 / 点击朗读 / 试听不出声、气泡报「语音合成失败」或日志里有 `WSServerHandshakeError` 时**先读**；改 `pet/edge_tts_endpoint.py`、`_TTSWorker._synthesize` 或升级 edge-tts 之前必读。 |
| [`PR-REPORT-SESSION-CARD-THEMES-2026-10-11.md`](PR-REPORT-SESSION-CARD-THEMES-2026-10-11.md) | 会话小鱼详情卡的配色方案：详情卡原先借用气泡样式的颜色，按钮底用的是气泡的**边框色**，在「吐气水泡」下按钮字与按钮底的对比度只有 1.32。改为 5 个命名好的固定方案（海盐青 / 奶油暖黄 / 素白纸张 / 深夜墨蓝 / 樱花粉），不开放自定义颜色；每个方案由测试逐项验 WCAG 对比度。入口在右键菜单「详情卡配色」。含每个方案的对比度表与「没有在真实桌面上点开确认」的登记。 | 改 `pet/session_card_themes.py`（新增或调整方案必须过对比度测试）、`SessionDetailCard` 的样式、会话小鱼菜单之前必读；想给别的界面做「几个预设里选」的配色时可照此做法；用户反馈「卡片上的字 / 按钮看不清」时必读。 |
| [`PR-REPORT-TRAY-ICON-CUSTOM-2026-10-11.md`](PR-REPORT-TRAY-ICON-CUSTOM-2026-10-11.md) | 自定义托盘图标：默认图标取自角色当前帧并等比缩进方格，实测只占方格的 52%（`shenshen`）/ 29%（`claude`）；新增设置「常规 → 窗口与系统 → 托盘图标」指定一张图片，没指定或文件用不了就回到角色头像，改完不用重启。含「自定义图片必须挡在首帧刷新轮询前面」「`Config.reload()` 是键白名单、新键不加读不回来」两个要点，以及「没有在真实托盘里人眼确认」的登记。 | 改 `pet/tray_icon.py`、`OverlayShell._tray_icon` / `_refresh_tray_icon_once` / 托盘首帧轮询、`settings_tray.py` 之前必读；**新增任何顶层配置键时**先看 §三 的白名单说明；用户反馈「托盘图标太小 / 设置了没变 / 过一会儿变回去了」时必读。 |
| [`PR-REPORT-REMOVE-PACKAGING-2026-10-11.md`](PR-REPORT-REMOVE-PACKAGING-2026-10-11.md) | 删除打包与发布部分：项目只从源码在本机运行，去掉三个平台的构建脚本、安装包定义、打包入口、四条构建 / 发布工作流、产物校验脚本与对应测试、两份打包指南（共 25 个文件）。列出了**故意留下**的东西：运行期里给打包版准备的分支（`sys.frozen`、`build_variant` 变体目录、无聊天变体的延迟导入约束）、`uninstall_cleanup`、PR 测试工作流。 | 想恢复打包 / 发布、或看到代码里的 `sys.frozen` / `build_variant` 分支想知道还有没有用时必读；找不到 `docs/ONEDIR_PACKAGING.md` / `STABLE_BUILDS.md` 或 `scripts/build_*` 时。 |
| [`PR-REPORT-BIG-FAT-FISH-RENAME-2026-10-11.md`](PR-REPORT-BIG-FAT-FISH-RENAME-2026-10-11.md) | 程序在系统里的名字从上游的 `dsh-pet-standalone` 改为 `big-fat-fish`：数据目录、钥匙串服务名、开机自启项、打包产物名、日志器名。重点是升级迁移——数据目录首次启动整目录改名（新目录已存在则逐项搬，绝不覆盖新数据）、钥匙串按需从旧服务名抄过来、属于本程序的旧自启项换名、已注入的 Claude Code 钩子（本机 + WSL）改到新路径（靠迁移留下的待办标记触发，平时不碰用户的 settings.json）。含真机迁移记录（167 个文件 1.4 ms、钩子 18 处全部切换、正在运行的 Claude Code 会话无需重启）与「打包 / CI / macOS / Linux 未验证」的登记。 | 改 `config.APP_DIR_NAME` / `migrate_legacy_app_dir`、`SecretStore` 的服务名、`autostart` 的标识与收编逻辑、`ClaudeCodeMonitor.refresh_hooks` 之前必读；用户反馈「升级后设置没了 / Key 要重填 / 开机启动两次 / 会话小鱼不动了」时必读；读旧报告遇到 `dsh-pet-standalone` 路径想知道现在对应什么时。 |
| [`PR-REPORT-GITHUB-CONNECTOR-2026-10-11.md`](PR-REPORT-GITHUB-CONNECTOR-2026-10-11.md) | GitHub 连接器：桌宠对话经 Messages API 的 MCP connector 只读查询 GitHub（仓库 / 提交 / Issue / PR），由 Anthropic 服务器去连 GitHub 官方远程 MCP 服务器，桌宠本地不跑 MCP 客户端。设置页「AI 与对话 → 连接器」一个开关 + Token（存系统钥匙串），默认关；只在直连 Claude API 的三个交互式对话入口生效，识屏等后台请求不挂。含实测：首段文字晚约 0.66 s、每条消息多约 1.23 万 token 缓存读、为什么要在 toolset 上单独打缓存断点、Token 失效时整条请求 400 的现场输出，以及「真实聊天窗打字未验证 / `pause_turn` 无实机样本」的登记。§九 追加「关于我」设置：一段用户写的说明（是谁、知识库在哪个仓库）追加在人设后面，三种人设来源下都保留；含「设置页 System Prompt 何时会被角色包人设整段顶替」的说明。§十 追加本地知识库：GitHub 仓库每天同步成本机副本（下载 zip、只留文本文件、原子替换），对话时用 `kb_read` / `kb_list` / `kb_search` 三个本地工具只读副本；Claude 通道第一次有了客户端工具循环。含与连接器的实测对比（输入约 6,600 对 28,800 token）。 | 改 `pet/chat/connectors.py`、`anthropic_provider._open_stream` 的工具 / beta / 缓存参数、对话入口的发送前准备、`PromptBuilder.build_messages` 的 system 消息拼接之前必读；改 `pet/chat/knowledge_base.py` / `knowledge_sync.py`、给 Claude 通道加新的本地工具、要接第二个连接器（Drive / Slack）、开放写工具、或遇到「开了连接器后对话全部 400」时必读。 |
| [`PR-REPORT-BIGFISH-AUTOSTART-README-ASSETS-2026-10-11.md`](PR-REPORT-BIGFISH-AUTOSTART-README-ASSETS-2026-10-11.md) | 三件小事的报告：源码运行的开机自启改用 `BigFish.exe`（已有的 `pythonw.exe` 条目在 `is_enabled()` 里自动升级，只认本检出自己写的那条）、主页 README 改写为 BigFatFish 的说明（上游原文保留在后）、13 张配图与 4 个原始素材入库（24.87 MB，网络收集、授权未逐张核实）。含全量测试 3 遍里 2 遍原生崩溃的记录与判断 | 改 `pet/autostart.py` 的命令或升级条件前；全量测试原生崩溃、想知道是不是新问题时；要动配图池或 README 开头时 |
| [`PR-REPORT-CLAUDE-CODE-SESSION-FISH-2026-10-11.md`](PR-REPORT-CLAUDE-CODE-SESSION-FISH-2026-10-11.md) | `feature/claude-session-fish` 合入 main 的总报告（38 个提交、144 个文件）：每个 Claude Code 会话一只小鱼（详情卡 / 跳到对话 / 专属菜单 / 进程不在自动离场）、Claude 通道（Anthropic Messages API，含识屏）、跨屏拖动（副屏视口，不是 sprite 换窗）、程序身份 BigFish（改名启动器）、气泡字体等线、动图配图、洗牌式抽取、聊天气泡与聊天窗同步、灵动岛的会话 / 最近的对话 / 今日用量、素材生成链与提示词入库。含各路径实测数字、真实鼠标跨屏拖拽与真实会话跳转的运行记录、逐项「未验证」登记，以及「往 conftest 加全局 autouse fixture 会引出潜伏原生崩溃」的排查记录。数字分「本报告会话实测」与「取自提交说明、未复测」两类。 | 改会话小鱼 / `claude_session_info` / `claude_session_jump`、跨屏（`overlay_viewport` / `overlay_screens`）、`shuffle_bag`、`app_identity` / `tools/make_launcher.py`、Claude 通道之前必读；全量测试在 `test_recovery_hints` 原生崩溃、或要动 `tests/conftest.py` 之前必读。协议细节看 [`AGENT_LINK_PROTOCOL.md`](AGENT_LINK_PROTOCOL.md) §3.1。 |
| [`PR-REPORT-TEMPLATE.md`](PR-REPORT-TEMPLATE.md) | PR 报告模板：三份交付证据（修改文件说明 / 性能分析 / 实机运行记录）的逐节骨架与判定标准。 | **开新 PR 写报告前必读并整份复制**；2026-09-22 起三份证据是硬要求（`AGENTS.md` Delivery evidence discipline），由 `tests/test_pr_report_discipline.py` 机器化校验。 |

---

## 交接

| 文档 | 一句话内容 | 何时必读 |
|---|---|---|
| [`DEV-HANDOVER.md`](DEV-HANDOVER.md) | 上游的开发交接文档（2026-09-16，基线 `feat/voice-chime`）：本地运行、改配置、加功能、跑测试的流程，§8.2/§8.3 是 PR 交付证据的细则。其中「重新打包」一节在本项目已不适用（打包 2026-10-11 删除）。 | 写 PR 报告前查三份证据的细则（`tests/test_pr_report_discipline.py` 要求它仍写明该要求）；新人上手先读 README 的「快速开始」与 `AGENTS.md`。 |

---

## agent 工作约定（`docs/agents/`）

| 文档 | 一句话内容 | 何时必读 |
|---|---|---|
| [`agents/domain.md`](agents/domain.md) | 单上下文仓库的领域文档约定：先读根 `CONTEXT.md`，再读相关 ADR，术语保持一致，与 ADR 冲突的方案要显式标注。 | 探索一个陌生领域、或提出可能与既有决策冲突的方案之前。 |
| [`agents/issue-tracker.md`](agents/issue-tracker.md) | Local Markdown issue tracker 约定：feature/spec/ticket 的目录结构与状态行格式。 | 创建或读取 issue、spec、ticket 时（`.scratch/<feature-slug>/`）。 |
| [`agents/triage-labels.md`](agents/triage-labels.md) | 五个标准 triage 状态的映射表与含义。 | 给 issue 打标签、或需要把外部角色名映射到本仓库状态名时。 |
| [`agents/handoff.md`](agents/handoff.md) | 工作交接约定：`.scratch/<feature-slug>/HANDOFF.md` 的必备字段与续作时的校验步骤。 | 跨任务/跨上下文窗口续作未完成工作时；开工前先读 handoff 并核对 `git status`。 |

---

## 已移出的上游文档

fork 时随上游带来、在本项目已没有对应东西的文档（发版稿、打包与 CI 踩坑、在线更新协议、DSH 调研、主动识屏设计稿、插件化路线、交接快照、上游的 PR 报告）于 2026-11-02 移出本仓库，清单与上游固定链接见 [`UPSTREAM.md`](UPSTREAM.md)。原先这里的「疑似过时/重复文档」登记的都是这些文档，随之撤掉。
