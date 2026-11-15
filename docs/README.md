# 文档

一个子系统一份，写的是**现在**的机制、不变量、取舍和排障办法。某次改动的过程和实测记录在对应 PR 的描述里，
不在这里。新文档必须在本页登记（`tests/test_pr_report_discipline.py` 会检查）。

仓库根目录还有：[`README.zh-CN.md`](../README.zh-CN.md)（是什么、怎么跑、功能清单）、
[`AGENTS.md`](../AGENTS.md)（工程纪律，改代码前必读）、[`CONTEXT.md`](../CONTEXT.md)（术语表）、
[`CHANGELOG.md`](../CHANGELOG.md)（用户看得见的变化）。

## 功能

| 文档 | 内容 | 什么时候读 |
|---|---|---|
| [会话小鱼](session-fish.md) | 每个 Claude Code 会话一只小鱼：生灭、认领、状态、冻结、标签、详情卡、护驾与列队 | 改小鱼的出场 / 退场 / 状态、hook 脚本、详情卡；小鱼状态不对时 |
| [跳到对话](session-jump.md) | 从小鱼或岛跳回会话所在的窗口；右键菜单里的 VS Code 工作区、Claude Desktop、Claude Code（WSL）入口 | 改跳转或这三条入口；VS Code / Claude Code 升级后跳转变差时 |
| [灵动岛](island.md) | 胶囊与卡片：摆放与停靠、置顶、最近的对话、消息记录、用量、连接图标 | 改岛的几何、卡片里任何一块、用量统计 |
| [通知](notifications.md) | 读 Windows 通知、自家弹窗、叠放规则、点击跳转 | 改通知读取 / 弹窗 / 跳转；通知看不见或点了没反应时 |
| [台词、人设与语音](persona-and-voice.md) | 肥鱼怎么说话：人设、台词预设、气泡配图、语音报时与合成 | 改台词预设、人设拼法、报时、语音合成；没声音时 |
| [公司侧助理](work-assistant.md) | 工作简报、Slack 关注、工作笔记：经 WSL 里公司账号的无界面 Claude Code | 改这三个功能、那条 `claude -p` 命令或放行的工具名单 |
| [个人侧助理](personal-assistant.md) | 个人简报、灵感记录、GitHub 连接器、本地知识库、「关于我」 | 改个人助理、连接器、知识库工具、system 的拼法 |
| [会话记忆蒸馏](memory-distill.md) | 从会话记录抽取候选、蒸馏成提案、人工审核、落盘 | 改抽取 / 蒸馏 / 审核 / 落盘的任何一环 |
| [配置全景](config-panorama.md) | 把两边和 AI 有关的配置画成一张本地地图页 | 给全景加节点 / 连线、改探针或页面 |

## 界面与配置

| 文档 | 内容 | 什么时候读 |
|---|---|---|
| [设置与右键菜单](settings-and-menu.md) | 设置进程、设置变更门禁、Metro 样式、模型服务列表、菜单布局树、已下线的入口 | **新增或改动任何设置项、菜单项之前** |
| [界面语言](i18n.md) | 中文 / English：查表层、键名规范、新增文案的步骤、有意不翻的东西 | **新增任何界面文字之前** |
| [配置与数据](config-and-data.md) | 配置写盘与损坏恢复、GitHub 备份、数据目录、程序在系统里的名字、开机自启 | 改配置读写、数据目录、自启；「设置全丢了」时 |

## 工程

| 文档 | 内容 | 什么时候读 |
|---|---|---|
| [决策记录](adr/README.md) | 长期有效的决定各一份，以及什么时候该写新的 | 想推翻一个现有做法之前；做大改动时 |
| [与上游的关系](upstream.md) | 上游旧文档去哪找、只从源码运行、挑拣同步的做法、帧序列档位、聊天窗生命周期 | 同步上游、想恢复打包、改帧序列或聊天窗关闭流程 |
| [`agents/`](agents/domain.md) | agent 的工作约定：[领域文档](agents/domain.md)、[issue](agents/issue-tracker.md)、[triage 标签](agents/triage-labels.md)、[交接](agents/handoff.md) | 用 `.scratch/` 记 issue、交接未完成的工作时 |

## 待并入的旧文档

下面这些是 fork 时带来的专题文档，内容仍然有效，下一步会并进上面的结构（架构总览、开发指南、排障手册）。
在那之前照旧引用它们。

| 文档 | 内容 |
|---|---|
| [`DEV-HANDOVER.md`](DEV-HANDOVER.md) | 上游的开发交接（2026-09）：分层、架构红线、语音报时实现。打包与行号已过时 |
| [`WINDOW_PY_SPLIT_GUIDE.md`](WINDOW_PY_SPLIT_GUIDE.md) | `pet/window.py` 的拆分办法与生命周期边界 |
| [`QT-LIFECYCLE-FULL-SUITE-STABILIZATION-2026-09.md`](QT-LIFECYCLE-FULL-SUITE-STABILIZATION-2026-09.md) | 全量测试原生崩溃的归因与诊断规则 |
| [`ISSUE-111-WINDOWS-SESSION-END-FFMPEG-2026-09-12.md`](ISSUE-111-WINDOWS-SESSION-END-FFMPEG-2026-09-12.md) | Windows 关机时的 ffmpeg 派生闸门 |
| [`PR-MERGE-LESSONS-2026-09-12.md`](PR-MERGE-LESSONS-2026-09-12.md) | 合并 PR 的三则教训 |
| [`NETWORK-PROXY-AND-VPN-2026-09-22.md`](NETWORK-PROXY-AND-VPN-2026-09-22.md) | 系统代理 / VPN 对联网功能的影响 |
| [`AGENT_LINK_PROTOCOL.md`](AGENT_LINK_PROTOCOL.md) | Agent 联动的事件协议（对外口径） |
| [`SETTINGS-CHANGE-GATES.md`](SETTINGS-CHANGE-GATES.md) | 已并入[设置与右键菜单](settings-and-menu.md)，代码注释还指着它 |
| [`CONTEXT-MENU-RESEARCH-AND-REFACTOR-2026-08-25.md`](CONTEXT-MENU-RESEARCH-AND-REFACTOR-2026-08-25.md) | 已并入[设置与右键菜单](settings-and-menu.md) |
| [`PERSONA-PHRASES-PRESET-STORAGE-2026-09-08.md`](PERSONA-PHRASES-PRESET-STORAGE-2026-09-08.md) | 已并入[台词、人设与语音](persona-and-voice.md) |
| [`ISSUE-EDGE-TTS-VOICE-DEPRECATION-2026-09-22.md`](ISSUE-EDGE-TTS-VOICE-DEPRECATION-2026-09-22.md) | 已并入[台词、人设与语音](persona-and-voice.md) |
| [`PERSONA-TEMPLATE-FIELD-ALIGNMENT-2026-09-05.md`](PERSONA-TEMPLATE-FIELD-ALIGNMENT-2026-09-05.md) | 台词模板变量对照表（真相在 `pet/persona_template.py`） |
