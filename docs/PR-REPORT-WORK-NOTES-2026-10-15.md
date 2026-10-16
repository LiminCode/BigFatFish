# PR 报告：工作笔记——随手记、公司 Claude 总结、到点提醒、存进 AI-Base-Memory

> **基线**：`5ec6548`（feat(menu): 「Claude Code（WSL）」新开的终端窗口摆到主屏左半边）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-15
> **范围**：12 个文件（实现 8、测试 3、文档 1）
> **关联**：[`PR-REPORT-WORK-BRIEFING-2026-10-12.md`](PR-REPORT-WORK-BRIEFING-2026-10-12.md)（同一条 WSL 通道、同一套只读红线）；
> [`PR-REPORT-CLAUDE-LAUNCHERS-2026-10-15.md`](PR-REPORT-CLAUDE-LAUNCHERS-2026-10-15.md)（同日的前一个功能）

## 一、核心特性

用户的工作流：随时丢进来一个 Slack 链接、Jira 链接或一段 Slack 片段；**原文逐字保留**；
WSL 里登录着公司账号的 Claude Code 顺着链接把那条消息 / 工单读一遍，写摘要，**决定下次提醒
的时机**；笔记是 Obsidian 风格的 Markdown，存在公司私有仓库 `AI-Base-Memory` 的 `note/`
目录（那个仓库以后要当公司 AI 的记忆库）；在工作简报窗口里新加一页看这些笔记。

用户 2026-10-15 的三个决定：仓库副本放哪（先选 WSL，实测 Obsidian 不认后改 Windows，见三）；
这次只做笔记本体 + 新标签页（Metro + 白天黑夜整窗重做放下一轮）；添加后立即后台总结。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 记一条 | 简报窗口「笔记」页顶部的输入框，Ctrl+Enter 或「记下」：立刻落盘成 `note/YYYY-MM-DD-HHMM-<标题>.md`，原文逐字进 `## 原文`。 |
| 2 | 公司 Claude 总结 | 落盘后起后台线程跑 `claude -p`（沿用简报那行命令：内置工具全关、只放行 Slack / Atlassian / 日历的读取类工具），它只返回一个 JSON：摘要、要点、`remind_at`、理由、标签；肥鱼自己写回文件。本机实测一条 9.7 秒。 |
| 3 | 提醒 | 每分钟看一眼：到点、笔记未完成、人在电脑前（没锁屏、10 分钟内动过键鼠）→ 留到点为止的提醒气泡，按钮「查看 / 稍后 1 小时 / 完成」；同一个时间点只提醒一次。 |
| 4 | 存进仓库 | 每次落盘后经 WSL 在 `/mnt/c/.../AI-Base-Memory` 里 `git add note && commit && pull --rebase && push`（串行、后台）；启动 30 秒后先 `pull` 一次。 |
| 5 | Obsidian | frontmatter（created / title / kind / status / remind_at / tags / links …）+ `# 标题` + 三节；「在 Obsidian 打开」走 `obsidian://open?vault=…&file=note/…`；仓库没登记成库时退回打开文件夹并提示一次。 |
| 6 | 手改也认 | 用户在 Obsidian 里改过的文件读得回来：缺节、缺字段、没 frontmatter 都容忍，原文一节原样取。 |

**红线 / 不变量**：Claude 只读（`--tools ''` + 只放行读取类连接器工具，和简报一字不差）；原文不动
（总结只改 frontmatter 和「AI 摘要」「提醒」两节）；笔记文字不进肥鱼的聊天上下文、不送语音合成、
不写进日志（日志只有秒数 / 轮数 / 条数）；公司凭证不出 WSL（git 在 WSL 里跑，SSH 密钥在那边）。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/work_notes.py` | +566 / −0 | 新模块，零 Qt。配置 `normalize`（`enabled` / `repo_dir` / `model`，默认目录 `%USERPROFILE%\WorkSpace\AI-Base-Memory`）；`Note` 数据类；`new_note`（取链接、分类 slack / jira / confluence / link / text、标题、文件名安全化）；Markdown 往返 `render` / `parse`（自写的最小 frontmatter 读写，不引 PyYAML；H2 分节）；`save`（临时文件 + `os.replace`）/ `load` / `load_all`；提示词 `build_prompt`、`parse_summary`（复用简报的 `_result_record` 与 Slack 关注的 `_json_object`，过去的提醒时间丢弃、标签清洗）、`summarize`（复用 `wb.claude_command`）、`apply_summary`；提醒 `due_reminders` / `mark_alerted` / `snooze` / `finish`；git `wsl_path`（`C:\…` → `/mnt/c/…`）、`sync_command` / `pull_command` / `sync` / `pull`；Obsidian `obsidian_vaults`（读 `%APPDATA%\obsidian\obsidian.json`）/ `obsidian_uri`；状态文件 `work-notes.json`。 |
| `pet/work_notes_service.py` | +288 / −0 | `WorkNotesService(QObject)`：文件读写在 GUI 线程；总结每条一个 daemon 线程，结果经 `_summary_done` 信号回 GUI 线程后**重新读文件再合并**（用户可能已在 Obsidian 改过）；git 操作一把锁串行；`QTimer` 每分钟 `check_reminders`；`stop` 用代数计数器丢弃迟到结果（照简报服务）。`summarize` / `sync` / `pull` / `spawn` / `now` / `active` / `opener` 全部可注入。 |
| `pet/work_notes_ui.py` | +312 / −0 | `WorkNotesPanel`：输入框（Ctrl+Enter）、列表（状态记号 + 标题 + 提醒时间）、全文（摘要在前、原文在后）、按钮（在 Obsidian 打开 / 重新总结 / 稍后 ▾ / 完成 / 打开文件夹）、状态行（git 错误、仓库副本缺失提示）。`WorkNotesController`：接服务与宿主，提醒走 `show_alert`（`alert_id="work-note:<name>"`，priority 1，sticky），总结失败冒一句。颜色沿用简报的 `_PALETTES`。 |
| `pet/work_briefing_ui.py` | +42 / −5 | 窗口改成 `QTabWidget`：简报原有内容进第一页「简报」，只有一页时标签栏隐藏；`add_tab` / `select_tab`；QSS 加平底标签样式。控制器加 `tab_providers`（建窗口时挂别的页）和 `open_window(tab=…)`。原有属性名（`body` / `meta_label` / `regenerate_btn` …）全部保留，既有 53 个简报测试不动。 |
| `pet/app.py` | +22 / −0 | `_start_work_notes`：简报接好之后建笔记服务 + 控制器（开关关着不建），把「笔记」页挂到简报控制器，`_overlay_shell.work_notes` 供菜单用。 |
| `pet/config.py` | +6 / −0 | 新键 `work_notes`：默认值、重载白名单、`set` 时重新规范化的键集合、`_normalize_pet_settings`。 |
| `pet/sprite_menu_facade.py` | +6 / −0 | `open_work_notes()`：简报窗口开到「笔记」页。 |
| `pet/context_menus/shared.py` | +2 / −0 | 「工作简报」子菜单里多一条「工作笔记」（只在壳接了笔记服务时出现）。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_work_notes.py` | +254 / −0 | 28 个纯逻辑用例：建笔记（原文逐字、分类、标题、文件名安全）；render/parse 往返、Obsidian 手改过的文件；原子落盘与排序；提示词含原文且只要 JSON；总结结果解析（过去时间丢弃、标签清洗、三种失败）；`summarize` 用的命令含只读放行与拒绝名单、提示词走 stdin、没 WSL 的说法；`apply_summary` 不动原文、失败不动笔记；到点提醒 / 已提醒 / 改时间再提醒；稍后 / 完成；`/mnt/c` 路径；git 命令顺序与失败；Obsidian URI 与库登记；配置默认值与坏值。 |
| `tests/test_work_notes_ui.py` | +339 / −0 | 17 个 Qt 用例：加一条 → 文件 / 总结 / 推送 / 信号；空的不记；总结失败保留笔记并报原因；git 失败进状态行；稍后 / 完成改文件并推送；提醒只在人在、到点、未提醒过时发一次，稍后之后再发；Obsidian 未登记退回文件夹；仓库副本缺失也能记；列表行与全文文字；面板录入与按钮状态；提醒气泡三个按钮各自的效果；简报窗口的标签栏只在第二页时出现；简报控制器挂页并开到指定页；菜单「工作笔记」有 / 无；`AppShell._start_work_notes` 开关。 |
| `tests/test_config_schema.py` | +1 / −0 | 重载白名单快照加 `work_notes`。 |

### 未改动

- 托盘、灵动岛：没加入口，简报按钮进去切页即可。
- 设置页：`work_notes` 没有设置页交互——`repo_dir` 有可靠默认值、`enabled` 默认开，这一轮和
  简报最初一样只走配置文件；要改目录就改配置里的 `work_notes.repo_dir`。按
  `SETTINGS-CHANGE-GATES` 的准入它是「偏好 + 低频 + 有默认」，下一轮做 Metro 重做时再进设置页。
- `pet/slack_watch_ui.py`：它复用 `WorkBriefingWindow`，改成标签页后它那扇窗口只有一页，标签栏
  隐藏，外观不变。

## 三、实现要点

- **仓库副本放 Windows、git 从 WSL 跑**。先按用户的选择克隆到 WSL `~/AI-Base-Memory`，然后
  实测 Obsidian：`obsidian://open?path=\\wsl.localhost\…`、映射盘 `W:\…`、甚至本机临时目录，
  三次都没登记成库——Obsidian 的 `open?path=` 只打开**已登记的库**里的路径，不新建库。
  用户给了 Obsidian 论坛那帖（Windows + Claude Code WSL2 共用一个库），共识是「库放 NTFS、
  WSL 经 /mnt/c 访问」；于是克隆挪到 `C:\Users\<user>\WorkSpace\AI-Base-Memory`（和用户的
  AI-Docs 库并排），`git config core.filemode false` + `core.autocrlf false`，提交推送经
  `wsl.exe -e bash -lc "cd /mnt/c/... && git …"`（SSH 密钥、公司 gh 登录都在 WSL）。实测
  `git status` 在 DrvFs 上 0.08 s，一次 add/commit/pull/push 3.5 s。
- **Obsidian 登记是一次性的手动动作**：用户在 Obsidian 里「Open folder as vault」选那个目录
  一次，之后「在 Obsidian 打开」就能直接跳到那条；没登记时肥鱼退回打开文件夹并提示一句。
- **frontmatter 自写**：仓库没有 PyYAML，也不想为几个键引依赖。写时字符串遇到 `: ` / 开头特殊
  字符就用 JSON 引号；读时认引号与裸值；列表 `  - `。Obsidian 的属性面板认这个子集。
- **总结回写前重读文件**：用户可能在总结那几十秒里在 Obsidian 改了标题或状态；GUI 线程拿到
  结果后 `load` 再 `apply_summary` 再 `save`，只覆盖摘要相关字段。
- **提醒去重**：状态文件记 `{笔记名: 提醒时间}`；同一时间点只发一次；稍后 / 重新总结改了时间
  就算新的一次。

## 四、性能分析

**方法（可复现）**：实机脚本（scratchpad `notes_real_run.py`：`new_note` → `save` → `summarize`
（真 `wsl.exe` + `claude -p`）→ `apply_summary` → `save` → `sync`（真 git push））；
环境：Windows 11 Pro 10.0.26300，Python 3.13（仓库 `.venv`），WSL Ubuntu-24.04，claude 2.1.300，
模型 sonnet，n=1（每跑一次算公司席位用量，不多跑）。

| 指标 | 实测 | 归属 |
|---|---|---|
| `claude -p` 总结一条纯文本笔记 | 9.7 s，1 轮 | 新增，每记一条 1 次（后台线程） |
| git add/commit/pull --rebase/push（经 wsl.exe，DrvFs） | 3.5 s | 新增，每次落盘 1 次（后台线程、串行） |
| `git status`（DrvFs，WSL 侧） | 0.08 s | 既有工具 |
| 本地读写 `note/*.md`（NTFS） | 毫秒级（GUI 线程） | 新增，每次操作 1 次 |
| 每分钟的提醒检查 | 读目录 + 解析所有 md（本机 1 条）+ 状态文件 | 新增，1/min；人不在时只做一次 `session_active` 探测就返回 |
| 启动 | `pull` 一次（30 s 延迟、后台）；页与面板**懒建**（打开窗口才建） | 新增 |

**结论**：① 稳态：多一个每分钟的 QTimer（人在时读一遍 `note/`，几条文件几毫秒）；窗口、面板
懒建，不开就不建；② 新增路径：记一条 ≈ 10 s 的 Claude + 3.5 s 的 git，全在后台线程，GUI
线程只做毫秒级文件读写；③ 新系统调用：每次操作一次 `wsl.exe`（git），每条一次 `wsl.exe`
（claude）；无新网络（git / claude 的网络在 WSL 侧）；新线程：每条总结一个、每次 git 一个，
daemon，用完即退；④ 内存：无缓存、无常驻列表（每次 `notes()` 重新读）。

## 五、实机运行记录

**前提**（2026-10-15）：

```
WSL: gh auth status → Logged in to github.com account lwang-sc
gh repo view lwang-sc/AI-Base-Memory → PRIVATE, main, 只有 README.md
Obsidian 1.14.4 装在 %LOCALAPPDATA%\Programs\Obsidian；登记的库：G:\My Drive\AI-Base、C:\Users\<user>\WorkSpace\AI-Docs（开着）
obsidian://open?path=<UNC> / <W:\…> / <本机临时目录> → 三次都没登记成库（obsidian.json 不变、目录里没出现 .obsidian）
UNC 读写 \\wsl.localhost\Ubuntu-24.04\home\<user>\AI-Base-Memory：写 4.5 ms、读 11 ms（能用，但 Obsidian 不认）
```

**仓库副本**：

```
$ cd /mnt/c/Users/<user>/WorkSpace && git clone -q git@github.com:lwang-sc/AI-Base-Memory.git
$ git config core.filemode false && git config core.autocrlf false
$ time git status → real 0m0.080s
```

**一条真实笔记走完全程**（纯文本、无链接，故意不碰公司 Slack / Jira）：

```
repo_dir: C:\Users\<user>\WorkSpace\AI-Base-Memory | notes_dir: …\AI-Base-Memory\note
saved: 2026-10-15-1940-明天上午和-Bob-对一下季度报告的提纲-周五前要发给-Amy.md
summarize: ok=True seconds=9.7 turns=1 denied=[] error=''
  summary: 明天上午和 Bob 对季度报告提纲，并在周五前把报告发给 Amy。
  remind_at: 2026-10-16T09:00:00 | reason: 明天上午要和 Bob 开会，而且“周五前”发给 Amy 的最晚期限就是明天，所以在上班开始时提醒。 | tags: ['季度报告', '会议', '截止']
  details: - 明天（周五 10-16）上午：和 Bob 对季度报告的提纲… / - 原文没有 Slack、Jira 或 Confluence 链接，没有读取外部背景，以上内容只来自笔记本身。
round-trip equal: True
sync: ok=True 3.5s out=''
obsidian uri: (仓库还没登记成库)
$ gh api repos/lwang-sc/AI-Base-Memory/commits → "note: 实机验证 | 2026-10-16T02:40:27Z"
$ gh api repos/lwang-sc/AI-Base-Memory/contents/note → 那一个 .md
```

模型自己说明了「没有链接、没读外部背景」，符合提示词要求；提醒定在明早 9 点并给了理由。

**用户可见行为**：肥鱼已重启（`acquired pid=54940`），日志无 Traceback（两条匹配 `Error` 的是
歌词服务 429 的 WARNING，与本次无关），启动 30 秒后的 `pull` 没有报错行。简报窗口里现在有
「简报 / 笔记」两页——**需要用户自己点灵动岛的简报按钮或右键「工作简报 → 工作笔记」看**；
本机没有能点真实窗口的自动化工具，面板的录入、列表、按钮、提醒气泡在
`tests/test_work_notes_ui.py` 用真实 `OverlayShell` + 真实 Qt 部件（offscreen）覆盖。

**边界与失败路径**：`wsl_claude_argv`-式的「没 WSL」在本机做不出真实场景，由测试覆盖；
「Obsidian 没登记成库 → 退回文件夹 + 提示」是本机此刻的真实状态（上面 `obsidian uri` 为空）。

**没验证的**：带 Slack 永久链接 / Jira 链接的笔记没在实机跑——会读到公司内容，而且本报告进公开
仓库；只读放行名单与简报完全相同（简报 2026-10-12 已实机验证过 Slack / Jira 的读取）。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 红灯 | `pytest -q tests/test_work_notes.py`（模块写出前） | 收集期 `ImportError` |
| 静态检查 | `.venv\Scripts\ruff.exe check pet tests` | All checks passed |
| 聚焦 | `pytest -q tests/test_work_notes.py tests/test_work_notes_ui.py` | 45 通过 |
| 相关 | `pytest -q … tests/test_work_briefing.py tests/test_work_briefing_links_and_island.py tests/test_slack_watch.py tests/test_config_schema.py` | 140 通过 |
| 受影响时序族 | 服务的线程 / 定时都注入成同步假函数，无真实时序 | 不适用 |
| 全量 | `python -m pytest -q -p no:cacheprovider`（offscreen，临时 APPDATA） | `4 failed, 5331 passed, 11 skipped in 541.22s (0:09:01)`。4 个失败全是本机既有的环境性基线（`test_image_directory_picker_…` 路径超 260；`test_festival_id_guard_survives_optimize` 与 `test_real_second_process_refused_on_overlay_topology` 子进程输出按 cp1252 解码；`test_capture_window_rect_coordinates_and_clamping` 多显示器负原点），与前一个 PR 的全量同一组；`tests/test_architecture.py` 在其中通过。 |

## 七、已知限制与后续

- 下一轮（用户已点名）：整个简报窗口 Metro 风格 + 白天 / 黑夜；`work_notes` 进设置页。
- Obsidian 登记要用户手动做一次；之后 `obsidian://` 直达。
- 列表没有搜索 / 过滤，笔记多了再加。
- 提醒只在肥鱼在跑、人在电脑前时发；离开期间到点的，回来后第一分钟补发。
- 仓库被别处改了（公司 AI 写记忆）：启动时 `pull`，每次 push 前 `pull --rebase`；中途别处的
  改动要到下次操作才看到。

## 八、风险与回滚

- 新配置键 `work_notes`（默认开、目录有默认值）；回滚 `git revert` 后旧版本会把这个未知键原样
  保留在配置文件里，不影响运行。
- 数据：笔记在 `AI-Base-Memory/note/`（用户的仓库，回滚不动它）；状态文件
  `%APPDATA%\big-fat-fish\work-notes.json` 只记提醒过的时间点，可删。
- 公司席位用量：每记一条约 10 秒的 `claude -p`；「重新总结」再来一次。
