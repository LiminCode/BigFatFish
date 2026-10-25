# PR 报告：DeepSeek 的入口全部下线——右键菜单、托盘、Agent 联动开关、设置页（2026-10-14）

> **基线**：`9a5837e`（chore(settings): 设置页里的 DeepSeek 痕迹下线，`feature/claude-session-fish`）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-14
> **范围**：26 个文件（实现 13、测试 11：新增 1、改 10、文档 2）
> **关联**：[`PR-REPORT-REMOVE-DEEPSEEK-SETTINGS-2026-10-14.md`](PR-REPORT-REMOVE-DEEPSEEK-SETTINGS-2026-10-14.md)（上一刀：设置页的余额节）、
> [`PR-REPORT-VSCODE-WORKSPACES-MENU-2026-10-13.md`](PR-REPORT-VSCODE-WORKSPACES-MENU-2026-10-13.md)（「音乐」「显示本轮消费」下线的同一口径）

## 一、核心特性

用户看了右键菜单「工具与帮助」里的「DeepSeek 余额 / DeepSeek Harness / 打开网页版 DeepSeek」之后说：这些都可以去掉，
其余 DeepSeek 的功能也一起。这一刀摘掉的**入口**：

| 位置 | 摘掉的 |
|---|---|
| 右键菜单「工具与帮助」 | 「DeepSeek 余额」「DeepSeek Harness」子菜单（启动 dsh web / 启动桌面端 / 重启 / 停止）「打开网页版 DeepSeek」；新版 / 旧版两套模板、注册表、`modern-default-v1` 布局都没有了，只剩「GitHub 项目页」 |
| 托盘菜单 | 同名三项（Chat 版的余额 + 两个启动项、纯桌宠版的网页版） |
| 右键「Agent 联动」 | 「DeepSeek Harness (DSH)」联动开关（其余 Claude Code / Claude Code (WSL) / Cursor / OpenCode 不变） |
| 设置页「常规 → 应用启动」 | 「随桌宠启动 dsh 服务」「自启目标」两行 |
| 设置页「互动 → 点击反馈」 | 「点击显示余额」 |
| 灵动岛「卡片内容」下拉 | 「服务商余额」项（值 `balance` 仍认，`auto` 的回落逻辑不变，只是不再可选） |
| README | 安装清单里的「启动 DeepSeek Harness」条、功能概览里的 Harness 长段、「DeepSeek 余额（Chat 版）」一节、托盘表格一行；更新日志里的历史记述原样 |

**保留的**（只摘入口，不删能力）：`pet/balance.py`（余额查询）、`pet/harness_launcher.py`（启动 / 重启 / 停止、自启门）、
`AppShell._maybe_autostart_harness`（读 `harness_autostart`，默认 False → 不动作）、`DshMonitor` 与 `agent_link.dsh`
配置、`click_show_balance` 的点击路径（`window.py` / `overlay_shell.py` 仍读配置）、`balance_*` / `harness_*` 配置键。
用户配置里已有的这些值不会被设置页保存覆盖（用例守着）。

**红线 / 不变量**：
- 三个 action id 进 `_MENU_LAYOUT_DROPPED_ACTIONS`：用户老布局里残留的节点在加载时清掉，不会被菜单编辑器回存成「此平台不可用」。
- 「工具与帮助」子菜单、「Agent 联动」子菜单、设置页各域各节的其余项不变；行 id 不变。
- 新版 / 旧版菜单的其它条目顺序不变（旧版的「工具」组整组没了，它只有 `harness` 一项）。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/context_menus/registry.py` | +2 / −10 | `ACTION_LABELS` / `ACTION_ICONS` / 动作表删 `balance` `harness` `deepseek_web`；对应 import 删。 |
| `pet/context_menus/shared.py` | +2 / −70 | 删 `add_balance`、`_dialog_parent` + `add_harness`、`open_deepseek_web` + `add_deepseek_web`、`DEEPSEEK_WEB_URL`、`launch_harness_gui` import；「Agent 联动」的 agents 列表删 `dsh`。 |
| `pet/context_menus/legacy.py` | +1 / −7 | 旧版建造器不再调 `add_harness` / `add_deepseek_web`。 |
| `pet/context_menu.py`、`pet/menu_templates/modern.json`、`legacy.json`、`modern-default-v1.json` | 共 +2 / −7 | 模板与默认布局里的三个 id 删掉（旧版的 `tools` 组随之整组删）。 |
| `pet/config.py` | +2 | `_MENU_LAYOUT_DROPPED_ACTIONS` += 三个 id。 |
| `pet/app.py` | +1 / −10 | 托盘菜单的三项与两个 import 删。 |
| `pet/modern_settings_dialog.py` | +2 / −79 | 删「随桌宠启动 dsh 服务」「自启目标」的控件构建、说明、行与保存；`claim("autostart")`；删 `harness_mod` import；删「点击显示余额」的保存。 |
| `pet/settings_pet_controls.py` | +2 / −6 | 删 `click_balance_check` 构建；「卡片内容」下拉去掉余额项。 |
| `pet/settings_interaction.py` | −10 | 删「点击显示余额」行。 |
| `README.md` | +5 / −14 | 见上表。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_deepseek_entries_removed.py`（新） | +90 | 注册表 / 两套模板 / 默认布局 / 兜底模板都没有三个 id，`dropped` 集合含它们；老布局载入时清掉三项、项目页还在；设置页没有三行、不落「待分类」、卡片内容下拉只剩 auto / claude、保存不覆盖旧配置值；shared 里的四个建造器不存在。 |
| `tests/test_menu_layout.py` | +3 / −24 | 注册 id 集合与「工具与帮助」期望更新；「点击显示余额」从互动页行清单去掉。 |
| `tests/test_sprite_menu_parity.py` | +3 / −42 | 必有标签 / 聊天门标签去掉三项；删 `test_harness_launcher_gets_widget_dialog_parent`。 |
| `tests/test_sprite_menu_target.py` | +1 / −25 | 删 `test_balance_gets_shell_as_parent`。 |
| `tests/test_desktop_pet_features.py` | +11 / −14 | 紧凑分组用例改点「GitHub 项目页」验证外链；纯桌宠用例改为「三项都不在」；旧版布局用例同。 |
| `tests/test_requested_regressions.py` | −147 | 删 5 个 harness 自启 / 自启目标 / README 段落的设置页用例。 |
| `tests/test_harness_lifecycle.py` | −103 | 删 3 个 Harness 子菜单用例（启动器本身的 30 个用例不动）。 |
| `tests/test_tray_icon_ready.py` | +5 / −6 | 托盘用例改为「三项都不在」。 |
| `tests/test_agent_link.py` | +2 / −1 | 「Agent 联动」四项 → 三项，断言 DSH 不在。 |
| `tests/test_update_entry_removed.py` | +2 / −1 | 默认布局断言改为「项目页在、三项不在」。 |
| `tests/test_settings_interaction_tabs.py` | +1 / −1 | 行清单去掉 `click_balance`。 |
| `tests/test_architecture.py` | +2 / −1 | 设置页行数预算 2373 → 2296。 |
| `tests/test_balance.py` | −14 | 删直接调 `add_balance` 的菜单用例（全量发现）。 |

## 三、实现要点

- 和「音乐」下线同一套办法：注册表 / 模板 / 建造器三处同时删，再把 id 写进 `_MENU_LAYOUT_DROPPED_ACTIONS`，老布局不留幽灵项。
- 「Agent 联动」里 DSH 开关摘掉但 `DshMonitor` 还在：`agent_link.dsh` 已经开着的人仍会跑监视器（改配置文件才能关）；
  要彻底删 DSH 联动是另一刀（`agent_link.py` 里 dsh 相关约 60 处）。
- 「卡片内容」保留 `balance` 值：`_island_card_source` 的 auto 逻辑在没开 Claude Code 联动时仍回落到余额卡片；用户机器上
  Claude Code 联动是开着的，所以看到的始终是会话卡。

## 四、性能分析

本改动只删入口（菜单项、托盘项、设置行）与 README，没有新增运行路径。

| 指标 | 实测 | 归属 |
|---|---|---|
| 右键菜单条目 | 「工具与帮助」4 → 1 项、「Agent 联动」5 → 4 项、托盘少 2–3 项 | 既有路径，构建更少 |
| 设置对话框 | 少 3 个控件 + 3 行（上一轮 ~300 个控件里 1%） | 既有路径 |

**结论**：① 稳态开销无变化（`_maybe_autostart_harness` 仍按配置默认 False 判一次就退）；② 没有新增路径；③ 没有新的
系统调用 / 线程；④ 内存少几个控件，可忽略。

## 五、实机运行记录

- **测试**：新增 4 用例全绿；菜单编排 / 菜单等价 / 菜单目标 / 桌宠功能 / 既往回归 / 托盘 / 下线守卫 / Harness 生命周期 /
  Agent 联动 / 架构守卫 / 设置资源族 `502 passed, 2 skipped`，失败 1 个是这台机器固定的 `image_directory_picker` 路径超 260。
  `ruff check pet tests` 通过。
- **真实桌面**：没有重新开真实右键菜单 / 托盘核对——改动是「删条目」，离屏用例按标签逐项断言不在。
- **全量**：见本节末尾。

**没有验证的部分**：托盘菜单在真实系统托盘里的样子（离屏构造覆盖）。

**全量结果**（隔离 worktree `bffv3` = 基线 `9a5837e` + 本补丁，`python -m pytest -q -p no:cacheprovider`，
`QT_QPA_PLATFORM=offscreen`、`APPDATA` 指到临时目录）：

```
6 failed, 5273 passed, 11 skipped, 248 warnings in 454.96s (0:07:34)
```

4 个是这台机器上固定的环境性失败（`image_directory_picker` 路径超 260、`festival_id_guard` 子进程按 cp1252 打印中文、
`real_second_process`、`capture_window_rect` 多显示器负原点）。另外 2 个是本改动漏改的、全量才跑到的用例，已修：
- `tests/test_balance.py::test_menu_balance_action_calls_bound_window_callback` 直接调已删掉的 `add_balance`——用例删掉（余额模块其余用例不动）。
- `tests/test_claude_link.py::test_menu_offers_the_wsl_channel_only_where_wsl_exists`：「Agent 联动」里 `Claude Code (WSL)` 按固定下标 2 插入，
  DSH 项没了之后落到了 Cursor 后面——改为下标 1（紧跟 Claude Code），用例本身不改。
两个文件 + Agent 联动 / 下线守卫族单跑 `232 passed`。
