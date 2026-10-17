# PR 报告：工作笔记页列表 / 详情改左右排 + 总结后标题换成内容概括

> **基线**：`dd824c3`（fix(menu): 右键菜单的直角系统阴影换成跟圆角走的软阴影）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-16
> **范围**：6 个文件（实现 3、测试 2、截图脚本 1）+ 本报告 + 2 张截图
> **关联**：[`PR-REPORT-WORK-NOTES-2026-10-15.md`](PR-REPORT-WORK-NOTES-2026-10-15.md)（笔记本体）、
> [`PR-REPORT-BRIEFING-METRO-2026-10-15.md`](PR-REPORT-BRIEFING-METRO-2026-10-15.md)（窗口样式）

## 一、核心特性

用户 2026-10-16 看着实机截图提了两点：「每条提醒和内容是上下分开的，可不可以做成左右模式」；「标题区分度不够，
当 Claude 总结发来之后需要更新标题，标题可以是内容的总结」。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 左右布局 | 列表在左、详情在右，中间是可拖的 `QSplitter`（默认 1 : 2，列表最窄 200、详情最窄 320，不可折叠）。之前上下排时窗口高 1100 也只给列表 300 多像素、详情被挤到下半截。 |
| 2 | 列表两行 | 列表变窄后「标题 · 提醒 10-16 17:37」一行放不下会被横向滚动条截掉：提醒改到第二行，横向滚动条关掉、超长标题右侧省略。 |
| 3 | 总结后换标题 | 提示词多要一个 `title`（≤ 20 字，概括这件事本身，明说不要「Slack 消息」「某人的消息」这种泛称）；`parse_summary` 取出、`apply_summary` 写回 `Note.title`（Claude 没给就保留原标题）。**文件名不变**（`name` 仍是记下时的 `日期-时间-slug`），Obsidian 里的链接、已推送的路径都不动；frontmatter 的 `title` 和正文一级标题会随新标题重写。 |

**不变量**：原文逐字不动；旧笔记文件（没有 `title` 字段变化的）照常读；「重新总结」会再换一次标题。

## 二、修改文件说明

| 文件 | 增删 | 改动 |
|---|---|---|
| `pet/work_notes.py` | +12 / −5 | `_PROMPT` 第 2 条加 `title` 的要求、输出 JSON 示例加 `"title"`；`SummaryResult.title`；`parse_summary` 取 `title`（压空白、截到 `MAX_TITLE_CHARS`）；`apply_summary` 写 `title=result.title or note.title`，docstring 说明文件名不变。 |
| `pet/work_notes_ui.py` | +18 / −5 | `WorkNotesPanel`：`QSplitter(Horizontal)` 装列表与详情（objectName `notesSplitter`），布局从「列表 2 : 详情 3 上下」改成分隔条占满中间；列表关横向滚动条、右侧省略；`row_label` 提醒另起一行。 |
| `pet/work_briefing_ui.py` | +1 / −0 | 样式表：`QSplitter#notesSplitter::handle` 透明、8px 宽（Metro 没有可见分隔线）。 |
| `scripts/capture_briefing_window.py` | +3 / −2 | 截图窗口宽度 640 → 1000（左右排要够宽）；样例笔记带 Claude 给的标题，截图里能看出「总结后标题换了」。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_work_notes.py` | +18 / −0 | 提示词含 `"title"`；回答里的 `title` 被取出、压空白、截长；`apply_summary` 换标题但 `name` 不变、往返 Markdown 后标题一致；没给标题就保留原来的。 |
| `tests/test_work_notes_ui.py` | +7 / −2 | 面板有水平 `QSplitter`，第 0 / 1 个子件是列表 / 详情；列表行两行格式（中 / 英各一处断言改成 `\n`）。 |

### 未改动

- 服务层（`work_notes_service.py`）：`apply_summary` 的返回值本来就整条落盘，标题跟着一起写进文件、一起 push，不用改。
- 提醒气泡用的是 `note.title`，自动用上新标题。

## 三、实现要点

- 标题只在 `apply_summary` 里换，而不是在 UI 层拼：这样 Obsidian 库里的文件、提醒气泡、列表看到的都是同一个标题。
- 文件名不跟着标题改：改名要处理 git mv、已有链接和已推送的路径，收益只是文件名好看一点；frontmatter 里的 `title`
  才是展示用的。

## 四、性能分析

| 指标 | 改动前 | 改动后 | 说明 |
|---|---|---|---|
| 提示词长度 | 约 1,020 字 | 约 1,110 字（+90 字，含示例） | 每次总结多约 60 个输入 token，相对实测一次总结 11 万～12 万输入 token（主要是工具读 Slack / Jira 的内容）可忽略 |
| 面板构建 | 1 个 `QVBoxLayout` | + 1 个 `QSplitter` | 一次性，打开简报窗口时 |
| 列表行 | 单行 | 带提醒的两行 | 行高翻倍，列表能看到的条数减半；左右排后列表高度是原来的 3 倍，净增 |

**结论**：① 稳态零开销；② 每条笔记总结多约 60 个输入 token（<0.1%）；③ 无新系统调用 / 网络 / 磁盘 / 线程；
④ 内存无变化。本机没有对面板做计时——改动是布局容器替换，不在任何热路径上。

## 五、实机运行记录

- **截图**（`QT_QPA_PLATFORM=windows` 真实字体，`scripts/capture_briefing_window.py`，样例数据）：
  `docs/screenshots/work-notes-layout-2026-10-16/notes-light-zh.png`（浅色中文）、`notes-dark-en.png`（深色英文）。
  看过：列表在左、详情在右，分隔条无可见线；带提醒的行是两行；第一条的标题是 Claude 给的概括而不是「Slack 消息」。
  第一版截图里深色列表底部有一条横向滚动条、行尾被截——这就是「列表两行 + 关横向滚动条」的来由。
- **红灯**：三个新断言在改动前运行均失败（提示词没有 `"title"`；`SummaryResult` 没有 `title` 字段；面板没有 `splitter`）。改后绿。
- 肥鱼已按常规方法重启（结束不含 `--settings` 的主进程，`run.bat` 拉起，日志无 Traceback）。用户现有的三条笔记标题
  不会自动变——要点一次「重新总结」才会拿到新标题（提示词是这次才加的）。真实总结结果（标题是否概括得好）依赖
  WSL 里的 Claude Code 和公司账号，本机没法自动验证；本报告只验证了字段链路。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `ruff check pet tests scripts` | All checks passed |
| 聚焦 + 相关 | `pytest -q tests/test_work_notes.py tests/test_work_notes_ui.py tests/test_briefing_metro.py tests/test_settings_work_notes.py tests/test_i18n.py tests/test_pr_report_discipline.py` | 214 通过 |
| 全量 | 未跑 | 改动限于笔记页的布局容器、一个提示词字段和它的解析 / 写回；不涉及共享模型 / 配置迁移 / 生命周期 / 线程 / 打包 / 平台分支；按 AGENTS.md 的「局部展示 token」豁免。 |

## 七、已知限制与后续

- 分隔条位置不记忆（每次打开都是 1 : 2）。
- 列表行里的提醒时间和标题同一种字号 / 颜色（`QListWidget` 纯文本行做不了两种样式；要的话换成自绘代理）。
- 标题由 Claude 概括，质量取决于它读没读到链接内容；读不到时它会按原文概括。

## 八、风险与回滚

- `git revert` 即可。已经被换过标题的笔记文件保留新标题（那是数据，不是代码）。
- 风险点：`title` 字段过长或含换行——已压空白、截到 60 字；frontmatter 写入走原有的转义。
