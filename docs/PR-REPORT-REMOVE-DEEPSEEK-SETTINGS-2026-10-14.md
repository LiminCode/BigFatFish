# PR 报告：设置页里的 DeepSeek 痕迹下线——「余额与服务状态」一节摘掉、文案去品牌（2026-10-14）

> **基线**：`7fb17d8`（feat(settings): 设置页改成 Windows Phone / Metro 风格，`feature/claude-session-fish`）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-14
> **范围**：10 个文件（实现 6、测试 3：新增 1、改 2、文档 1）
> **关联**：[`PR-REPORT-VSCODE-WORKSPACES-MENU-2026-10-13.md`](PR-REPORT-VSCODE-WORKSPACES-MENU-2026-10-13.md)（第二轮「显示本轮消费」下线，同一口径）

## 一、核心特性

用户用的是 Claude，DeepSeek 的东西用不到了（2026-10-13 已先摘掉「显示本轮消费」）。这次把设置页里剩下的：

| 位置 | 以前 | 现在 |
|---|---|---|
| AI 与对话 → **余额与服务状态**（5 行：余额自动刷新、峰谷提示文案、高峰 / 空闲自定义文本、峰谷提示颜色） | 一整节 | **整节下线**：行、控件、保存都删掉；配置键与余额代码保留（旧配置里的值原样留着，保存设置页不会动它们） |
| 桌面组件 → 卡片内容 的说明 | 「…否则显示 DeepSeek 余额与峰谷」 | 「…否则显示服务商余额」；下拉里「DeepSeek 余额」改叫「服务商余额」（值 `balance` 不变） |
| AI 与对话 → 每日请求上限 的说明 | 「DeepSeek 视觉单次约 ¥0.003…」 | 「每天最多发多少次识屏请求…」 |
| 对话窗口风格名 | 「肥鱼版 DeepSeek」 | 「**肥鱼版宽屏**」（`CHAT_UI_STYLE_LABELS["modern"]`，三处说明、裁切取景行标题随之；配置值 `modern` 不变） |

**红线 / 不变量**：
- 配置格式一个键没动：`balance_refresh_minutes`、`balance_tier_*`、`dynamic_island.card_source`、`chat_ui_style` 的取值集合都不变，旧配置读进来照样认。
- 余额查询（`pet/balance.py`）、灵动岛余额卡片、`balance_refresh_minutes` 的后台定时都还在——只是没有设置页入口；要改只能改配置文件。
- 设置页其余节、域、行 id 不变；下线不靠把行丢进「待分类」（用例守着）。

**没动的 DeepSeek 痕迹**（另议）：右键菜单里的「DeepSeek 余额」、「打开网页版 DeepSeek」、「DeepSeek Harness (DSH)」
子菜单，互动页的「点击显示余额」，以及 AI 服务商列表里的 DeepSeek 供应商项——这些是菜单注册表 / 联动功能的一部分，
不在「设置页文案」这一刀里。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/modern_settings_dialog.py` | +4 / −36 | 删「后台服务」节的构建（5 行）、`claim_prefix("balance_")` 与「余额与服务状态」的放置、保存里的 5 个 `config.set`；两条说明文字去品牌。留一行注释说明去向。 |
| `pet/settings_pet_controls.py` | +2 / −28 | 删 5 个余额控件的构建（`balance_refresh_spin` 等）；灵动岛「卡片内容」下拉的 `balance` 项改名「服务商余额」。 |
| `pet/chat/themes.py` | +1 / −1 | `CHAT_UI_STYLE_LABELS["modern"]`：「肥鱼版 DeepSeek」→「肥鱼版宽屏」。 |
| `pet/chat/ai_settings_page.py` | +4 / −4 | 三条说明文字与一条注释随风格名改。 |
| `pet/chat/settings_dialog.py`、`pet/config.py` | +1 / −1 各 | 注释随风格名改。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_balance_settings_removed.py`（新） | +73 | 五行与两个节名都不在、没有落进「待分类」、控件属性不存在；保存设置页不动旧配置里的三个余额键；设置页所有说明文字里没有「DeepSeek」。 |
| `tests/test_chat_subsystem.py` | +7 / −7 | 风格名断言改为「肥鱼版宽屏」。 |
| `tests/test_desktop_pet_features.py` | +2 / −2 | 同上。 |
| `tests/test_architecture.py` | +2 / −1 | 设置页行数预算 2405 → 2373（删掉的那三处）。 |

## 三、实现要点

- 和「显示本轮消费」同一口径：只摘入口，不删数据与代码；用户配置文件里已有的值不被设置页保存覆盖。
- 风格名改的是标签表的一个值；配置里存的是 `modern` / `classic`，所以改名不涉及迁移。
- 「服务商余额」这个值（`balance`）保留：`AppShell._island_card_source` 的 auto 逻辑还会在没开 Claude Code 联动时落到它。

## 四、性能分析

**方法**：本改动只删控件与改字符串，没有新增运行路径。可量化的只有设置页构建少了 5 个控件：

| 指标 | 实测 | 归属 |
|---|---|---|
| 设置对话框建好并显示（离屏，九页全建） | 401 ms（Metro 那轮量的，含这 5 个控件）→ 本轮没有重量；5 个控件在 ~300 个控件里占比 < 2% | 既有路径 |

**结论**：① 稳态开销无变化；② 没有新增路径；③ 没有新的系统调用 / 线程；④ 内存少 5 个控件，可忽略。

## 五、实机运行记录

- **测试**：`tests/test_balance_settings_removed.py` 3 用例全绿；聊天子系统 / 聊天主题 / 设置资源 / 架构守卫 / 桌宠功能 /
  既往回归 / 岛接线族 `351 passed, 2 skipped`，失败 1 个是这台机器固定的 `image_directory_picker` 路径超 260。
  `ruff check pet tests` 通过。
- **真实窗口**：没有重新开真实设置窗口核对——改动是「少一节 + 改几个字」，离屏用例直接断言了节不在、字不在。
- **全量**：没有重跑。改动不涉及接口、持久数据、生命周期、平台分支；按 AGENTS 的局部控件口径以焦点 + 相关族为准
  （上一提交的全量是 20 分钟前跑的，基线一致）。

**没有验证的部分**：右键菜单与灵动岛余额卡片的真实行为（没动它们的代码）。
