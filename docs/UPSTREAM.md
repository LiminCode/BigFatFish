# 上游文档（已移出本仓库）

本项目 fork 自 [MerZlin/dsh-pet-indesktop](https://github.com/MerZlin/dsh-pet-indesktop) 的 `main@ee699c7`（2026-10-06）。
下面这些文档是 fork 时随上游带来的，描述的是上游项目（发版、安装包、DSH、插件化路线、上游 PR 等），
在本项目里已经没有对应的东西，2026-11-02 移出了本仓库。每一条都链到上游 `ee699c7` 那个版本，
上游以后改了或删了也打得开；本仓库的 git 历史里同样能找回（`git show ee699c7:docs/<文件名>`）。

**仍然有效的上游文档留在 `docs/`**：它们还约束着现在的代码（`AGENTS.md` 的 Context pointers 或测试点了名），
比如 [`SETTINGS-CHANGE-GATES.md`](SETTINGS-CHANGE-GATES.md)、[`ISSUE-111-WINDOWS-SESSION-END-FFMPEG-2026-09-12.md`](ISSUE-111-WINDOWS-SESSION-END-FFMPEG-2026-09-12.md)、
[`PR-MERGE-LESSONS-2026-09-12.md`](PR-MERGE-LESSONS-2026-09-12.md)。完整清单见 [`INDEX.md`](INDEX.md)。

上游 README 的原文（安装、使用教程、动画素材、开发结构、v4.x 变更记录）：
[README.md @ ee699c7](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/README.md)。

## 发版、打包与在线更新

本项目只从源码运行，没有安装包、不发版、没有在线更新（见 [`PR-REPORT-REMOVE-PACKAGING-2026-10-11.md`](PR-REPORT-REMOVE-PACKAGING-2026-10-11.md)）。

| 文档 | 标题 |
|---|---|
| [`ACCEPTANCE_TESTS.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/ACCEPTANCE_TESTS.md) | 验收测试文件清单 |
| [`BUILD-CI-FAILURE-NOTES-2026-08.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/BUILD-CI-FAILURE-NOTES-2026-08.md) | 打包与 CI 失败经验（持续更新） |
| [`BUILD_ARTIFACTS-2026-08-22.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/BUILD_ARTIFACTS-2026-08-22.md) | 2026-08-22 构建产物记录 |
| [`CHANGELOG-DEV-SINCE-v4.1.0-2026-09-09.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/CHANGELOG-DEV-SINCE-v4.1.0-2026-09-09.md) | 自 v4.1.0 发布以来的开发版变更汇总 |
| [`ONLINE-UPDATE.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/ONLINE-UPDATE.md) | 在线更新协议与发布清单 |
| [`PR-REPORT-ONLINE-UPDATE-2026-09-24.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-ONLINE-UPDATE-2026-09-24.md) | 在线更新功能 PR 报告（2026-09-24） |
| [`RELEASE-v4.2.0.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/RELEASE-v4.2.0.md) | v4.2.0 |
| [`RELEASE-v4.2.1.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/RELEASE-v4.2.1.md) | v4.2.1 |

## 插件化 / DLC 路线（上游规划，本项目没有实施）

| 文档 | 标题 |
|---|---|
| [`plugin-phase-01-foundation/PLUGIN-API-CONTRACT.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/plugin-phase-01-foundation/PLUGIN-API-CONTRACT.md) | 插件 API 合同（v1） |
| [`plugin-phase-01-foundation/PLUGIN-DLC-ARCHITECTURE.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/plugin-phase-01-foundation/PLUGIN-DLC-ARCHITECTURE.md) | 插件化 / DLC 化架构基线（v5 重建） |
| [`plugin-phase-01-foundation/PLUGIN-MIGRATION-v4-to-v5.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/plugin-phase-01-foundation/PLUGIN-MIGRATION-v4-to-v5.md) | v4 → v5 插件化数据迁移说明 |
| [`plugin-phase-02-runtime/README.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/plugin-phase-02-runtime/README.md) | Phase 2：Core 插件运行时 |
| [`plugin-phase-03-worker/PHASE3_PROCESS_PLUGIN_RESEARCH.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/plugin-phase-03-worker/PHASE3_PROCESS_PLUGIN_RESEARCH.md) | Phase 3：独立进程 / 插件化容器调研与设计 |
| [`plugin-phase-03-worker/README.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/plugin-phase-03-worker/README.md) | Phase 3：Worker 插件运行时 |
| [`plugin-phase-04-updates/PLUGIN-UPDATE-PROTOCOL.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/plugin-phase-04-updates/PLUGIN-UPDATE-PROTOCOL.md) | Core 与 DLC 更新协议 |
| [`plugin-phase-04-updates/README.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/plugin-phase-04-updates/README.md) | Phase 4：DLC 更新中心 |
| [`plugin-phase-05-distribution/README.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/plugin-phase-05-distribution/README.md) | Phase 5：通用 DLC 分发适配 |
| [`plugin-phase-06-ecosystem/README.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/plugin-phase-06-ecosystem/README.md) | Phase 6：第三方插件生态 |
| [`plugin-phase-07-release/README.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/plugin-phase-07-release/README.md) | Phase 7：跨平台正式发布 |
| [`plugin-roadmap/PLUGIN-DLC-ROADMAP-v5.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/plugin-roadmap/PLUGIN-DLC-ROADMAP-v5.md) | v5 插件化 / DLC 分阶段路线图 |

## 设置与菜单重构（2026-08～09）

现行的设置页是 Metro 风格（[`PR-REPORT-SETTINGS-METRO-2026-10-14.md`](PR-REPORT-SETTINGS-METRO-2026-10-14.md)）；改设置仍以 [`SETTINGS-CHANGE-GATES.md`](SETTINGS-CHANGE-GATES.md) 为准。

| 文档 | 标题 |
|---|---|
| [`SETTINGS-INFORMATION-ARCHITECTURE-2026-08-27.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/SETTINGS-INFORMATION-ARCHITECTURE-2026-08-27.md) | 桌宠设置页信息架构重组记录 |
| [`SETTINGS-REDESIGN-IMPLEMENTATION-LOG.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/SETTINGS-REDESIGN-IMPLEMENTATION-LOG.md) | 设置与菜单重构：实现及踩坑记录 |
| [`SETTINGS-REDESIGN-Q4-CLASSIFICATION-RESEARCH.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/SETTINGS-REDESIGN-Q4-CLASSIFICATION-RESEARCH.md) | 桌宠设置重构 Q4：侧栏分类调研 |
| [`SETTINGS-REDESIGN-Q5-OTTY-C…X-VISUAL-RESEARCH.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/SETTINGS-REDESIGN-Q5-OTTY-%43ODEX-VISUAL-RESEARCH.md) | 桌宠设置重构 Q5：Otty 与 某外部编程工具 视觉调研 |
| [`SETTINGS-REDESIGN-Q6-Q7-DOMAIN-LAYOUT-DECISION.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/SETTINGS-REDESIGN-Q6-Q7-DOMAIN-LAYOUT-DECISION.md) | 设置重构 Q6/Q7：能力域、布局系统与 UI Skill 评估 |
| [`SETTINGS-REDESIGN-UI-ACCEPTANCE.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/SETTINGS-REDESIGN-UI-ACCEPTANCE.md) | 设置页逐页 UI 验收 |
| [`SETTINGS-REPORT-PROBABILITY-2026-09-10.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/SETTINGS-REPORT-PROBABILITY-2026-09-10.md) | 设置变更记录：事件汇报概率门 report_gates（2026-09-10） |

## DSH 与 Agent 联动

DSH 的入口已于 2026-10-14 下线（代码保留）；事件协议的现行口径见 [`AGENT_LINK_PROTOCOL.md`](AGENT_LINK_PROTOCOL.md)。

| 文档 | 标题 |
|---|---|
| [`AGENT_LINK_LIVE_TEST.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/AGENT_LINK_LIVE_TEST.md) | Agent 联动实机测试说明（交给 Kimi Code） |
| [`DSH-BRIDGE-PET-EVENT-CONTRACT-2026-09-02.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/DSH-BRIDGE-PET-EVENT-CONTRACT-2026-09-02.md) | Agent 适配器 → Pet 事件契约与接口说明 |
| [`DSH-HUMAN-REQUEST-RESEARCH-2026-09-02.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/DSH-HUMAN-REQUEST-RESEARCH-2026-09-02.md) | DSH 人工请求事件调研与 Bridge 说明 |
| [`DSH-REQUEST-EVENT-CATALOG.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/DSH-REQUEST-EVENT-CATALOG.md) | DSH human-request event catalog |
| [`OPEN-SOURCE-HARNESS-RISK-RESEARCH.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/OPEN-SOURCE-HARNESS-RISK-RESEARCH.md) | 开源 Harness 风险与轨迹设计调研 |
| [`PET-STATE-MACHINE-AND-REPETITION-2026-09-02.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PET-STATE-MACHINE-AND-REPETITION-2026-09-02.md) | Pet 状态机与重复检查说明 |

## 主动识屏

| 文档 | 标题 |
|---|---|
| [`PROACTIVE_SCREEN_IMPLEMENTATION_MANUAL.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PROACTIVE_SCREEN_IMPLEMENTATION_MANUAL.md) | 主动识屏 + 多 Agent 联动 — 实施手册（Kimi K3 终审版） |
| [`PROACTIVE_SCREEN_PLAN.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PROACTIVE_SCREEN_PLAN.md) | 主动识屏（Proactive Screen Watch）与多 Agent 感知 — 已验证设计方案 |
| [`issue-draft-主动识屏v420.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/issue-draft-%E4%B8%BB%E5%8A%A8%E8%AF%86%E5%B1%8Fv420.md) | Issue 草稿：v4.2.0 单进程共享模式下主动识屏永不触发 |

## 交接、阶段快照与一次性记录

| 文档 | 标题 |
|---|---|
| [`BUGFIX-AND-FEATURES-2026-08-24.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/BUGFIX-AND-FEATURES-2026-08-24.md) | 桌宠焦点、图标与“生小肥鱼”开发记录 |
| [`CHAT-BACKGROUND-DISPLAY-2026-08-27.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/CHAT-BACKGROUND-DISPLAY-2026-08-27.md) | AI 对话背景显示调整记录（2026-08-27） |
| [`HANDOVER_2026-09.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/HANDOVER_2026-09.md) | dsh-pet 性能+结构线交付手册（2026-09-03） |
| [`OPTIMIZATION_CHECKLIST.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/OPTIMIZATION_CHECKLIST.md) | 性能优化复核清单（给 Kimi Code 独立验证） |
| [`PROJECT_HANDOFF.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PROJECT_HANDOFF.md) | 项目交接文档 — dsh-pet-pr（主动识屏 + 多 Agent 联动） |
| [`UPSTREAM-INTEGRATION-2026-08-26.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/UPSTREAM-INTEGRATION-2026-08-26.md) | 上游合并与新版 UI 收敛记录（2026-08-26） |
| [`grill-2026-08-21-ai-chat.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/grill-2026-08-21-ai-chat.md) | 桌宠 AI 对话功能需求对齐记录 |

## 上游的 PR 报告

fork 之前上游合并的 PR 的报告。本项目自己的 PR 报告仍在 `docs/`，登记在 [`INDEX.md`](INDEX.md)「PR 报告存档」。

| 文档 | 标题 |
|---|---|
| [`PR-REPORT-ARCHITECTURE-FAIR-COMPARISON-2026-09-26.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-ARCHITECTURE-FAIR-COMPARISON-2026-09-26.md) | PR 报告：新旧架构公平性能对照（基础比较完成 / 最终候选发布验收未完成） |
| [`PR-REPORT-FESTIVAL-REMINDER-2026-09-16.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-FESTIVAL-REMINDER-2026-09-16.md) | 节日提醒（festival_reminder）PR 报告 |
| [`PR-REPORT-FLIGHT-BEH-BATCH-2026-09-27.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-FLIGHT-BEH-BATCH-2026-09-27.md) | PR 报告：飞行期禁气泡 + 飞行边沿 + 落地预热去重（F-BEH 批次） |
| [`PR-REPORT-FRAMESEQ-V3-PIPELINE-2026-09-29.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-FRAMESEQ-V3-PIPELINE-2026-09-29.md) | 帧序列统一档位 v3（`unblend-white-v3`）全量重出与打包部署（2026-09-29） |
| [`PR-REPORT-FULL-REVIEW-FIXES-2026-10-03.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-FULL-REVIEW-FIXES-2026-10-03.md) | PR 报告：全量大审修复批次（21 条已验证缺陷） |
| [`PR-REPORT-GATES-2026-09-10.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-GATES-2026-09-10.md) | PR：事件汇报统一为概率门（report_gates） |
| [`PR-REPORT-GUI-IDLE-JANK-2026-09-29.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-GUI-IDLE-JANK-2026-09-29.md) | GUI 空转与卡顿批次（I3 + F-PERF + G + H）：岛撞收敛、慢爬重绘、气泡跟随、轮询风暴、事件过滤器快路径、死窗口守卫（2026-09-29） |
| [`PR-REPORT-HARNESS-DUAL-TARGET-2026-10-06.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-HARNESS-DUAL-TARGET-2026-10-06.md) | PR 报告：Harness 双目标启动（dsh web / 桌面端）+ 尾项收口（2026-10-06） |
| [`PR-REPORT-HARNESS-OWNERSHIP-2026-09-29.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-HARNESS-OWNERSHIP-2026-09-29.md) | node 桥门控收紧与退出归属收口（K1 + K2）（2026-09-29） |
| [`PR-REPORT-ISLAND-HIDDEN-CHAT-DEADLOCK-2026-09-23.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-ISLAND-HIDDEN-CHAT-DEADLOCK-2026-09-23.md) | PR 报告：纯桌宠版岛隐藏死锁修复（hidden_chat 路由回退） |
| [`PR-REPORT-ISLAND-RESHOW-NOCHAT-2026-09-23.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-ISLAND-RESHOW-NOCHAT-2026-09-23.md) | PR 报告：纯桌宠版「桌宠隐藏后单击灵动岛无反应」（2026-09-23） |
| [`PR-REPORT-ISLAND-TOPMOST-2026-09-29.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-ISLAND-TOPMOST-2026-09-29.md) | 灵动岛置顶性丢失（岛被盖住后永不回位）修复（ISLAND-TOPMOST）（2026-09-29） |
| [`PR-REPORT-ISSUE-186-TRAY-MENU-2026-09-23.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-ISSUE-186-TRAY-MENU-2026-09-23.md) | PR 报告：issue #186 恢复多显示器跨屏拖拽/抛掷 + 托盘图标消失 + 右键菜单「鼠标穿透」去重（2026-09-23） |
| [`PR-REPORT-LOCAL-WIP-BATCH-2026-09-22.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-LOCAL-WIP-BATCH-2026-09-22.md) | 本地 WIP 批次：交付证据纪律 + 构建 Qt 排他 + 产物 TTS 自检 + 角色头部框（2026-09-22） |
| [`PR-REPORT-MEMORY-DIET-SINGLE-PET-2026-09-24.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-MEMORY-DIET-SINGLE-PET-2026-09-24.md) | 内存瘦身专项报告（单宠稳态）：+170MB 归属拆解 + 两刀落地 |
| [`PR-REPORT-MEMORY-POLLING-BATCH-2026-09-29.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-MEMORY-POLLING-BATCH-2026-09-29.md) | 内存与轮询批次（M1/M2/M3 + N1/N2/N3）：帧表去物化、菜单树泄漏、过采样缓存、桥目录轮询真 bug（2026-09-29） |
| [`PR-REPORT-MUSIC-LYRIC-SYSTEM-PROXY-2026-09-22.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-MUSIC-LYRIC-SYSTEM-PROXY-2026-09-22.md) | PR 报告：歌词取词被系统代理拖死 + 网易云「歌词对齐」被误关（2026-09-22） |
| [`PR-REPORT-MUSIC-PLAYER-PATHS-2026-09-22.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-MUSIC-PLAYER-PATHS-2026-09-22.md) | 音乐播放器路径进设置页（`music_player_paths`）变更记录 |
| [`PR-REPORT-OVERLAY-MENU-PARITY-2026-09-24.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-OVERLAY-MENU-PARITY-2026-09-24.md) | PR 报告：overlay 右键菜单完整 parity（模板感知 + 缺失条目补齐） |
| [`PR-REPORT-OVERLAY-REGRESSION-FIXES-2026-09-24.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-OVERLAY-REGRESSION-FIXES-2026-09-24.md) | PR 报告：overlay 架构六类实机回归修复 + 上游 main 同步（2026-09-24） |
| [`PR-REPORT-OVERLAY-REVIEW-FIXES-2026-09-24.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-OVERLAY-REVIEW-FIXES-2026-09-24.md) | PR 报告：overlay 双端全量审查收口（DS 34 条 + GPT 3 条）（2026-09-24） |
| [`PR-REPORT-PERF-ISLAND-CONSOLIDATED-2026-09-23.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-PERF-ISLAND-CONSOLIDATED-2026-09-23.md) | PR 报告：流畅度/解码减负 + 岛远端硬墙 + 音效缓存 + 设置收口（2026-09-23） |
| [`PR-REPORT-PHASE4-4-RETIRE-MULTIPROCESS-2026-09-23.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-PHASE4-4-RETIRE-MULTIPROCESS-2026-09-23.md) | PR 报告：Phase 4.4a/4.4b 多进程多宠退役层（停用 → 删除） |
| [`PR-REPORT-PR76-2026-09-10.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-PR76-2026-09-10.md) | PR Report: 事件汇报概率门 + Persona 模板升级 + 全链路错误语义统一 |
| [`PR-REPORT-QT-LIFECYCLE-CRASH-FAMILY-2026-10-04.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-QT-LIFECYCLE-CRASH-FAMILY-2026-10-04.md) | PR 报告：Qt 生命周期崩溃家族根治（frameseq 在途交付 UAF + 配图加载线程堆） |
| [`PR-REPORT-REFRESHRATE-REWIRE-2026-09-30.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-REFRESHRATE-REWIRE-2026-09-30.md) | PR 报告：同分辨率切刷新率 tick 不重读（refreshRateChanged 接线） |
| [`PR-REPORT-SELF-TALK-IMAGE-CHANCE-2026-09-20.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-SELF-TALK-IMAGE-CHANCE-2026-09-20.md) | 自言自语「配图概率」（self_talk_image_chance）变更记录 |
| [`PR-REPORT-SELF-TALK-PRECACHE-2026-09-20.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-SELF-TALK-PRECACHE-2026-09-20.md) | 台词本地语音预缓存（self_talk_voice_precache_enabled）变更记录 |
| [`PR-REPORT-SETTINGS-INTERACTION-TABS-2026-09-22.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-SETTINGS-INTERACTION-TABS-2026-09-22.md) | 「互动」域设置页分页 + 抽 `pet/settings_interaction.py` 变更记录 |
| [`PR-REPORT-SHARED-MEDIA-LIBRARY-2026-09-29.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-SHARED-MEDIA-LIBRARY-2026-09-29.md) | 同角色多宠共享只读媒体视图 + 首帧解码跨库复用（SHAREDLIB）（2026-09-29） |
| [`PR-REPORT-SINGLE-OVERLAY-WINDOW-2026-09-24.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-SINGLE-OVERLAY-WINDOW-2026-09-24.md) | PR 报告：单合成窗（overlay）新架构产品化 + 帧序列化 B 档 |
| [`PR-REPORT-SMTC-MEDIA-TYPE-2026-10-06.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-SMTC-MEDIA-TYPE-2026-10-06.md) | PR 报告：SMTC 视频被当歌曲（媒体类型否决 + 浏览器会话开关） |
| [`PR-REPORT-STALE-CLIP-PAUSE-FREEZE-2026-10-03.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-STALE-CLIP-PAUSE-FREEZE-2026-10-03.md) | PR 报告：clip 暂停标记跨绑定滞留致画面永久冻结（拖拽/走路/挂机三症同源） |
| [`PR-REPORT-THROWN-ISLAND-PUMP-2026-09-24.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-THROWN-ISLAND-PUMP-2026-09-24.md) | PR 报告：thrown × 岛静态成员碰撞泵能根修（2026-09-24） |
| [`PR-REPORT-VOICE-CHIME-2026-09-15.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-VOICE-CHIME-2026-09-15.md) | PR Report: 语音报时（voice_chime）—— 调度判定 + edge-tts 合成播放 + 设置页接入 + 纯逻辑测试补齐 |
| [`PR-REPORT-VOICE-CHIME-DAILY-QUOTES-2026-09-28.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-VOICE-CHIME-DAILY-QUOTES-2026-09-28.md) | PR 报告：语音报时台词「每天整套换新」（修「每天同一时刻同一句」） |
| [`PR-REPORT-WINDOWS-PARITY-JANK-2026-09-27.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-WINDOWS-PARITY-JANK-2026-09-27.md) | Windows 专项报告：旧版功能继承收口 + 卡顿取证（2026-09-27） |
| [`PR-REPORT-music-lyric-2026-09-16.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-music-lyric-2026-09-16.md) | 人工说明 |
| [`PR-REPORT-music-lyric-align-2026-09-22.md`](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/PR-REPORT-music-lyric-align-2026-09-22.md) | 歌词对齐（`music_lyric_align`）PR 报告 |

## 截图

上游这几组截图也一并移出：`music-player-paths-2026-09-22/`、`self-talk-2026-09-22/`、
`settings-interaction-tabs-2026-09-22/`、`todo-reminder/`，以及 `settings-redesign/` 里 iteration-1～9 的截图。
在上游的 [docs/screenshots @ ee699c7](https://github.com/MerZlin/dsh-pet-indesktop/tree/ee699c7/docs/screenshots)。`settings-redesign/` 里本项目自己截的 iteration-10（Metro）留在本仓库。
