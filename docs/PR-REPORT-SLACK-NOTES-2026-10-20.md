# PR 报告：Slack 关注每条存成仓库 `slack/` 下的 Markdown + 简报窗口新「Slack 关注」页（查看 / 稍后 / 完成，到点再提醒）

> **基线**：`eff99da2`（fix(i18n): 切换界面语言后运行中的肥鱼真正切过去）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-20
> **范围**：8 个实现文件（含 2 张语言表）+ 1 个新测试文件 + 1 个旧测试断言 + 截图脚本 + 4 张截图 + 本报告
> **关联**：[`PR-REPORT-SLACK-WATCH-2026-10-14.md`](PR-REPORT-SLACK-WATCH-2026-10-14.md)（Slack 关注）、
> [`PR-REPORT-WORK-NOTES-2026-10-15.md`](PR-REPORT-WORK-NOTES-2026-10-15.md)（工作笔记：同一仓库、同一条 git 通道、同一套提醒）

## 一、核心特性

用户 2026-10-20：「我需要在 AI Base 的目录中加一个 markdown 目录存放每一条 slack 总结，防止错过，另外在工作简报再加一个
tab，就叫 Slack 关注，把每一条按照最新最前顺序放在前面，同时支持查看、稍后 X 小时、完成。另外，稍后 X 小时，当时间到时，
大肥鱼会再次冒气泡提醒我吧？」

此前 Slack 关注只在气泡里冒一次、全文在一个独立窗口里显示最近一次的结果；上一次的条目被下一次覆盖，点了「知道了」就没了。

| # | 改动 | 说明 |
|---|---|---|
| 1 | 每条落盘 | Slack 关注每次查到的**新**条目（`fresh`）各存成 `AI-Base-Memory/slack/<日期-时分>-<标题>.md`，和工作笔记同一种 Obsidian 格式（frontmatter + 原文 + AI 摘要 + 提醒三节）；`kind: slack`、标签 `work/slack`（急的再加 `urgent`）；原文记来源 · 标题 + 链接。不让 Claude 再读一遍（条目本身就是它的一句话总结），只是存起来。 |
| 2 | 不重复 | 同一批里重复的链接只存一次；下次查到已经存过的链接（没链接的按「来源 · 标题」）不再存、不再推；同一分钟同一标题的第二条文件名加 `-2`，不覆盖。 |
| 3 | 一起推送 | `SYNC_PATHS` 多了 `slack`：每次提交带上 `note/`、`slack/`、`.obsidian`；两个服务共用一把进程级 git 锁（两把锁会撞 `.git/index.lock`）。提交说明 `slack: N 条` / `slack: 稍后再提醒` / `slack: 完成`。 |
| 4 | 「Slack 关注」页 | 简报窗口第三页（简报 / 笔记 / Slack 关注），复用笔记页：没有输入框，最新的在最前；按钮：**查看**（在浏览器 / Slack 里开那条链接；没链接就开到列表里那条）、在 Obsidian 打开、重新总结（想让公司 Claude 顺着链接读一遍写摘要时用）、**稍后 ▾**（1 小时 / 3 小时 / 明早 9 点）、**完成**、删除、打开文件夹。 |
| 5 | 到点再提醒 | 稍后 = 给那条写上 `remind_at`；同一套每分钟的 `check_reminders`：到点、人在电脑前 → 肥鱼再冒一次留到点为止的气泡「查看 / 稍后 1 小时 / 完成」（副标题「Slack 关注 · 标题」，`alert_type=slack_watch`）；完成后不再提醒。**回答用户的问题：会。** |
| 6 | 总提醒多一个按钮 | 新条目的那个总提醒从「查看 / 知道了」变成「查看 / 稍后 1 小时 / 知道了」：稍后 = 这批都放到一小时后、到点逐条提醒；查看 = 开到「Slack 关注」页并选中第一条（以前开独立窗口；右键菜单的「Slack 关注」仍开那个窗口）。 |
| 7 | 设置页说明 | 「自动化与联动 → Slack 关注」末尾加一行「存档与『Slack 关注』页」说明；工作笔记的「这个功能怎么运作」加第 6 步。要工作笔记开着才存（同一个仓库）。 |

## 二、修改文件说明

| 文件 | 增删 | 改动 |
|---|---|---|
| `pet/work_notes.py` | +33 / −6 | `SLACK_DIR = "slack"`、`SLACK_TAG`；`SYNC_PATHS` 加 `slack`；`notes_dir(settings, folder)`、`obsidian_uri(..., folder)` 多一个目录参数；新 `note_from_slack_item(item, now)`（Slack 条目 → `Note`）、`unique_name(folder, name)`。 |
| `pet/work_notes_service.py` | +59 / −11 | 构造多 `folder` / `label` / `pull_on_start`；`notes_dir()` 用 `folder`；提交说明前缀用 `label`；进程级 `_GIT_LOCK`；新 `add_slack_items(items)`（去重、逐条落盘、一次推送）、`open_link(name)`；`start()` 按 `pull_on_start` 决定要不要启动时 pull（slack 服务不 pull，笔记服务已经拉过同一个仓库）。 |
| `pet/work_notes_ui.py` | +35 / −10 | `SLACK_ALERT_PREFIX`；面板 `slack=True`：隐藏输入框与「记下」、提示文案换、多一个「查看」按钮（`view_requested`）；控制器 `slack=True`：`view(name)`（开链接，退回开列表）、提醒的副标题 / 前缀 / `alert_type` 分开、提醒的「查看」走 `view`。 |
| `pet/slack_watch_ui.py` | +36 / −5 | 构造多 `notes=`（Slack 关注页的控制器）；`_on_finished` 先 `_archive(fresh)` 再冒总提醒；有 `notes` 时多「稍后 1 小时」（`_on_snooze`：这批全部 `snooze(60)`）；`_on_view` 开到那一页并选中第一条。 |
| `pet/app.py` | +33 / −1 | 新 `_start_slack_notes()`：工作笔记开着、简报窗口在 → 建 `WorkNotesService(folder=slack, label=slack, pull_on_start=False)` + `WorkNotesController(slack=True)`，页挂到 `briefing.tab_providers`，`self._slack_notes` / `shell.slack_notes`；`_start_slack_watch` 把它交给 `SlackWatchController(notes=…)`。 |
| `pet/settings_slack_watch.py` | +2 / −0 | 末尾一行 `help_row`（存档与「Slack 关注」页）。 |
| `pet/locale/zh.json`、`en.json` | 各 +8 / −2 | `slack.notes.hint.empty / button.view / button.view_hint / alert.subtitle / flow / flow_title`（6 个新键）；`notes.settings.flow_tooltip` 加第 6 步。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_slack_notes.py`（新） | +262 | Slack 条目 → 笔记（名字 / kind / 链接 / 标签 / 原文；`slack` 在 `SYNC_PATHS` 与 sync 命令里）；服务存新条目一次、同批去重、一次推送 `slack: 2 条`、不让 Claude 总结、再查同样的不存不推、最新最前；同分钟同标题不覆盖；**稍后 3 小时 → 2 小时后不提醒、3 小时 1 分后冒气泡「查看 / 稍后 1 小时 / 完成」，查看开链接、稍后再推 1 小时、完成后不再提醒**；没链接的查看开到列表；页面无输入框有查看按钮、顺序、点查看开链接、英文；总提醒「查看 / 稍后 1 小时 / 知道了」、稍后把两条都放到一小时后、查看开到那页选中第一条、再查同样的不重复；没接页时总提醒照旧；接线函数（笔记开着挂页、关着不挂）。 |
| `tests/test_work_notes.py` | +1 / −1 | sync 命令的断言加上 `'slack'`。 |

### 其他

| 文件 | 说明 |
|---|---|
| `scripts/capture_slack_notes_page.py`（新） | 「Slack 关注」页白天 / 黑夜 × 中 / 英四张截图（中性样例、临时目录、`USERPROFILE=C:\Users\me`）。 |
| `docs/screenshots/slack-notes-2026-10-20/*.png` | 4 张。 |

## 三、实现要点

- **复用而不是再造**：一条 Slack 关注就是一条「没总结过、没定提醒」的笔记——`Note` / 落盘 / 稍后 / 完成 / 提醒 / Obsidian / git 全部沿用，
  只给服务加了「存哪个目录、提交说明前缀」两个参数和一个批量存入口；面板和控制器各一个 `slack` 开关。
- **去重两层**：Slack 关注自己的状态文件（`alerted` 最近 200 个键）决定哪些是新的；存入口再按已存文件的链接 / 首行去重，状态文件被清也不会重复存。
- **不改 Slack 关注的提示词和通道**：Claude 侧一字未动，仍只放行 Slack 只读工具；存档不额外调用模型。
- **git 锁改成进程级**：以前每个服务一把；现在同一仓库两个服务串行。

## 四、性能分析

| 指标 | 实测 / 说明 |
|---|---|
| 新路径触发频率 | 只在 Slack 关注查到**新**条目时（用户机器上 15 分钟一查，多数时候 0 条新） |
| 存一批 | 每条一次 `os.replace` 原子写（本地 NTFS，毫秒级）+ 一次后台 git（和笔记同一条路径，之前实测 3.5 s / 次），在后台线程 |
| 稳态 | 多一个 `QTimer` 每 60 s 读一遍 `slack/*.md`（和笔记那个同款；目录小，毫秒级）；没有新线程常驻、没有新网络 / 系统调用 |
| 内存 | 一个 `WorkNotesService` + 一页面板（打开窗口时才建） |
| 新测试 | 10 例 0.9 s；相关 10 个文件 133 例 4.9 s |

## 五、实机运行记录

- **红灯**：`tests/test_slack_notes.py` 在实现前整个文件导入失败（`SLACK_ALERT_PREFIX` 不存在）；实现后 10 例全绿，
  `tests/test_work_notes.py` 里 sync 命令那条按预期红（命令里多了 `'slack'`），断言更新后绿。
- **截图**：`QT_QPA_PLATFORM=windows python scripts/capture_slack_notes_page.py docs/screenshots/slack-notes-2026-10-20`
  → 四张；中文白天：列表「○ 设计稿第 3 版 / ● 私信（提醒 10-20 13:29）/ ✓ 问你发布窗口定了没」，底部按钮
  「查看 · 在 Obsidian 打开 · 重新总结 · 稍后 ▾ · 完成 · 删除 · 打开文件夹」；英文黑夜对应 Open / Later ▾ / Done。
- **肥鱼已重启**（`pet-overlay-gate.log`：`10:58:41 acquired pid=45604`），`pet-45604.log` 38 行无 Traceback、无「接线失败」。
  用户机器上 Slack 关注开着（15 分钟一查）、工作笔记开着（仓库 `WorkSpace\AI-Base-Memory`），最近一次检查 10:53 返回 0 条，
  `slack/` 目录要等下一次查到有「需要你看的」时才会出现——这是功能的触发条件，不是缺陷；不为了取证手动烧一次公司席位。
- 本报告与测试里的 Slack 条目都是中性样例（`example.slack.com`、「发布窗口」「周会」），不含真实消息。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `ruff check pet tests scripts` | All checks passed |
| 聚焦 + 相关 | `pytest -q tests/test_slack_notes.py tests/test_slack_watch.py tests/test_work_notes.py tests/test_work_notes_ui.py tests/test_work_notes_push_status.py tests/test_i18n.py tests/test_settings_english.py tests/test_briefing_metro.py tests/test_work_briefing_links_and_island.py tests/test_rest_english.py` | 133 通过 |
| 设置页 | `pytest -q tests/test_settings_slack_watch.py tests/test_menu_layout.py …` | 195 + 75 通过（自动化页加了一行说明，宽度门未动） |
| 全量 | `APPDATA=<临时> QT_QPA_PLATFORM=offscreen pytest -q -p no:cacheprovider tests` | 见下（改了服务 / 应用接线 / 设置页，跨多个测试域） |

全量结果：**5 failed, 5495 passed, 11 skipped，628.9 s**——5 个失败全是本机既有的环境性基线（图片选择器路径超 260、两个 cp1252 子进程输出、多显示器负原点、从 Git Bash 启动时的 `test_catalog_animation_count_guard_survives_optimize`），与本次改动无关。

补充实机：重启后 11:08:42 的自动 Slack 检查已跑完（状态文件 `last_ok` 更新、0 条、无错误、日志无 Traceback）。

## 七、已知限制与后续

- 存档要工作笔记开着（同一仓库）；笔记关着时 Slack 关注照旧只冒气泡。
- 「重新总结」对 Slack 条目也可用（公司 Claude 顺着链接读一遍写摘要、定提醒），但不自动做——每条都是一次真实调用。
- 笔记与 Slack 两个服务各自每 60 s 查一次提醒（两个目录），没有合并成一个定时器。
- 右键菜单「Agent 联动 → Slack 关注」仍开独立窗口（最近一次结果）；条目的操作在简报窗口的「Slack 关注」页。

## 八、风险与回滚

- `git revert` 即可；已存进 `slack/` 的文件是普通 Markdown，留着也不碍事。
- `SYNC_PATHS` 多了 `slack`：旧版本的 sync 命令不会带它，仅影响推送范围。
