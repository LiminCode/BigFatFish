# PR 报告：工作简报窗口改 Windows Phone / Metro 风格 + 白天 / 黑夜 + 中英文

> **基线**：`b1fb1e2`（feat(work-notes): 提交时带上 .obsidian 库配置）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-15
> **范围**：6 个文件（实现 5、测试 2、脚本 1、文档 / 截图）
> **关联**：[`PR-REPORT-WORK-NOTES-2026-10-15.md`](PR-REPORT-WORK-NOTES-2026-10-15.md)（「笔记」页就在这扇窗里）；
> `docs/screenshots/settings-redesign/iteration-10-metro-*`（设置页的 Metro 基准）

## 一、核心特性

用户 2026-10-15：「整个简报窗口改 Metro 风格 + 白天 / 黑夜，注意中英文支持」。简报窗口
（`WorkBriefingWindow`，也被 Slack 关注复用，并承载工作笔记的「笔记」页）改成和设置页同一套
Windows Phone / Metro 语言，主题跟随「外观」里的 system / light / dark，窗口右上角可当场切换，
全部文字走语言表。

| # | 能力 | 说明 |
|---|---|---|
| 1 | Metro 外观 | 小字应用名 + **pivot 页头**（28px / 细体，「简报 / 笔记」，选中的用标题色，其余灰），平铺的磁贴（正文、列表、全文：无描边、方角），输入框 2px 透明描边、聚焦主题色，按钮 2px 描边、透明底、按下反色、会朝光标倾斜（`TiltButton`）。颜色令牌直接用 `settings_theme_qss.METRO_TOKENS`，另加链接色与小标签色两组。 |
| 2 | 白天 / 黑夜 | 开窗口时读 `context_menu_appearance.theme`（设置页「外观」里那个）；右上角 ☾ / ☀ 当场切换整扇窗（样式表、正文链接与小标签、挂上来的「笔记」页），并把 light / dark 写回同一个偏好，设置页与菜单跟着变。 |
| 3 | 中英文 | 简报窗口、Slack 关注窗口、两者的气泡与提醒按钮共 27 个键进 `pet/locale`，跟随 `ui_language`；英文下应用名大写（`DAILY BRIEFING`），换语言后重开窗口生效。 |
| 4 | 证据 | `scripts/capture_briefing_window.py` 把窗口在 light / dark × zh / en × 简报 / 笔记 渲染成 8 张 PNG（`docs/screenshots/briefing-metro-2026-10-15/`）。 |

**红线 / 不变量**：既有简报 / Slack 关注 / 笔记的行为与属性名（`body` / `meta_label` / `regenerate_btn` /
`title_label` / `tabs` / `add_tab` / `select_tab`）不变，原有用例不动即过；样式表没有任何
非零圆角（`test_the_briefing_stylesheet_is_square_and_uses_the_metro_tokens` 守着）；主题偏好只有一个
来源（`context_menu_appearance.theme`）。

## 二、修改文件说明

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/work_briefing_ui.py` | +175 / −63 | 重写：`briefing_tokens(dark)` = `METRO_TOKENS` + 链接 / 小标签色；`resolve_dark(theme)`；Metro 样式表（含 pivot、磁贴、按钮、滚动条，也覆盖「笔记」页的控件）；窗口改成 应用名行 + ☾/☀ 按钮 + pivot 页头，按钮换 `TiltButton`，`apply_theme` / `toggle_theme` / `theme_changed`，`add_tab` 时给页套色；`theme_preference` / `save_theme_preference` 读写 `context_menu_appearance.theme`；控制器建窗口时传主题、切换时落盘；所有文案走 `t`。 |
| `pet/work_notes_ui.py` | +19 / −21 | 删掉自己的圆角样式表（由窗口的 Metro 样式表按 objectName 接管）；按钮换 `TiltButton`；`apply_theme(colors)` 换正文链接色；默认色板按「外观」主题取。 |
| `pet/slack_watch_ui.py` | +12 / −12 | 文案走 `t`；窗口传 `page_label="Slack"` 与主题，切换时落盘。 |
| `pet/locale/zh.json`、`pet/locale/en.json` | +28 / −1、+28 / −1 | `briefing.*`、`slack.*` 共 27 个键。 |
| `scripts/capture_briefing_window.py` | +74 / −0 | 渲染证据脚本（样例简报 + 两条样例笔记，不碰真实数据目录）。 |
| `.agents/skills/desktop-pet-ui-style/references/visual-system.md` | +16 / −0 | 记一节「简报 / 笔记窗口」：复用令牌、pivot 页头、额外两组色。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_briefing_metro.py` | +179 / −0 | 样式表无非零圆角、令牌落表、pivot 字号 / 字重；明暗的链接 / 小标签色不同；`resolve_dark`；按钮是 `TiltButton`、页头一直显示；切换白天 / 黑夜改样式表、改「笔记」页色、发 `theme_changed`；正文链接与小标签取主题色；控制器开窗口跟「外观」主题、切换写回并落盘；简报窗口与气泡英文；Slack 窗口英文；两张表都有全部 `briefing.*` / `slack.*` 键。 |
| `tests/test_work_notes_ui.py` | +3 / −3 | 「只有一页时隐藏标签栏」改成「pivot 页头一直显示」。 |

### 未改动

- 设置页、菜单：主题偏好的键没变，只是多了一个写入者（简报窗口的 ☾/☀）。
- 灵动岛：它自己那套平铺风格不动。

## 三、实现要点

- **一张样式表管整扇窗**：「笔记」页的控件靠 objectName（`notesInput` / `notesList` / `notesDetail` …）被窗口的
  样式表选中，面板不再带自己的样式表，换主题只要窗口 `setStyleSheet` 一次；面板只需换正文链接的调色板。
- **pivot 页头一直显示**：Windows Phone 的 pivot 哪怕一页也有页头；Slack 关注那扇窗的页头是「Slack」。
- **主题只有一个来源**：没有给简报窗口单独加主题键（`SETTINGS-CHANGE-GATES`：一个偏好一个归属）。
  切换按钮写回「外观」的主题，所以设置页与右键菜单会跟着一起变——这是刻意的「全局白天 / 黑夜」。
- **offscreen 没字体**：第一版截图是方块（offscreen 平台没有字体），改用 `QT_QPA_PLATFORM=windows` 跑
  脚本才有字；脚本两种平台都能跑。

## 四、性能分析

**方法**：本改动不触动任何常驻路径，只改窗口的构建与样式表。数字来自 scratchpad 脚本
`measure_briefing_window.py`（`QT_QPA_PLATFORM=windows`，建一扇带样例简报 + 两条样例笔记的窗口并显示、再切一次主题，n=10）
与 `len(_QSS.format(**tokens))`。

| 指标 | 实测 | 归属 |
|---|---|---|
| 样式表长度 | 2348 字节，`format` 一次 | 开窗口 1 次、切换主题 1 次 |
| 建一扇带两页的窗口并显示（含样例内容排版） | n=10：中位 92.0 ms，最大 299.4 ms（第一次含字体加载） | 用户点开时 1 次 |
| 切换主题（`setStyleSheet` + 重上色正文 + 面板换调色板） | n=10：中位 11.7 ms，最大 16.5 ms | 点 ☾/☀ 时 1 次 |

**结论**：① 稳态零开销（不开窗什么都不跑）；② 新增路径只在开窗 / 切换主题时各跑一次；③ 新增系统
调用：切换主题时写一次配置文件（和设置页保存同一条路）；无网络、无线程；④ 内存：窗口多持有一份
令牌 dict（十几个字符串）。

## 五、实机运行记录

- 渲染证据（`QT_QPA_PLATFORM=windows`，真实字体）：`docs/screenshots/briefing-metro-2026-10-15/` 下
  `briefing|notes` × `light|dark` × `zh|en` 共 8 张，逐张看过：应用名行 + 右上角 ☾/☀、pivot 页头
  「简报 笔记」、平铺正文（链接蓝、状态小标签灰）、右下角两颗方角描边按钮；笔记页的输入框、列表
  （选中 = 主题色底白字）、全文、五颗按钮；黑夜版对应深色令牌。第一版用 offscreen 抓出来全是方块
  （没字体），不算证据，已重抓。
- 肥鱼已重启（`acquired pid=54736`，日志无 Traceback）。右键「工作简报 → 查看最近一份」或岛上的按钮
  能看到新样式——**需要用户自己点**；本机没有能点真实窗口的自动化工具。
- 边界：`resolve_dark("system")` 在本机跟随系统（当前为浅色）；切换按钮写回偏好后设置页会跟着变，
  属预期。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 红灯 | 旧用例 `test_the_briefing_window_shows_a_tab_bar_only_with_a_second_page` 在新窗口上先失败（页头一直显示） | 已改成新口径 |
| 静态检查 | `ruff check pet tests scripts` | All checks passed |
| 聚焦 + 相关 | `pytest -q tests/test_briefing_metro.py tests/test_work_briefing.py tests/test_work_briefing_links_and_island.py tests/test_slack_watch.py tests/test_work_notes_ui.py tests/test_i18n.py tests/test_settings_metro.py` | 134 通过 |
| 全量 | `python -m pytest -q -p no:cacheprovider`（offscreen，临时 APPDATA） | `4 failed, 5348 passed, 11 skipped in 485.66s (0:08:05)`。4 个失败全是本机既有的环境性基线（`test_image_directory_picker_…` 路径超 260；`test_festival_id_guard_survives_optimize` 与 `test_real_second_process_refused_on_overlay_topology` 子进程输出按 cp1252 解码；`test_capture_window_rect_coordinates_and_clamping` 多显示器负原点），与前几个 PR 的全量同一组。 |

## 七、已知限制与后续

- 换界面语言后已经开着的窗口不会就地翻译，重开生效（和笔记页一致）。
- `work_notes` 进设置页 + 悬停解释流程的浮动图标：下一轮。
- 标签在全文里用行内代码渲染成等宽字；若想做成磁贴式小标签，走 `_decorate` 的 chip 路径即可。

## 八、风险与回滚

- 纯界面改动，无配置迁移；`git revert` 即可。切换按钮写过的 `context_menu_appearance.theme` 是既有键、
  既有取值，回滚后照常。
