# PR 报告：个人助理——灵动岛人形图标 → 个人简报（自己的 Claude 读 AI-Base）/ 灵感记录（推 GitHub）/ 在 Obsidian 打开

> **基线**：`61a7b05`（feat(work-notes): 笔记页列表 / 详情改左右排）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-17
> **范围**：22 个文件（实现 5 新 + 7 改、测试 6 新 + 2 改、脚本 2 新）+ 本报告 + 8 张截图
> **关联**：[`PR-REPORT-WORK-BRIEFING-2026-10-12.md`](PR-REPORT-WORK-BRIEFING-2026-10-12.md)（窗口壳与定时模式）、
> [`PR-REPORT-WORK-NOTES-2026-10-15.md`](PR-REPORT-WORK-NOTES-2026-10-15.md)（git 推送与 Obsidian 的经验）、
> [`PR-REPORT-GITHUB-CONNECTOR-2026-10-11.md`](PR-REPORT-GITHUB-CONNECTOR-2026-10-11.md) §十（本地知识库工具）

## 一、核心特性

用户 2026-10-17：肥鱼的简报 / 笔记都面向公司账号（WSL 里的 Claude Code）；要一条**面向个人**的线，基于个人知识库
仓库 AI-Base（Obsidian 风格，本地有 git 克隆）：灵动岛上加一个个人图标，点开能看个人简报、在 Obsidian 打开 AI-Base、
随手记灵感并自动推到 GitHub；界面要写明**是哪个 AI 在处理、怎么处理**。用户定的几条：处理的 AI 是**肥鱼自己的
个人 API key**（不经 WSL、不碰公司席位）；「登记进食」跳过；灵感写进单文件 `User/灵感 Inspiration.md`；模型与
思考强度要能**单独选**。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 岛上的人形图标 | 排在工作简报图标右边、铃铛左边；`hidden / idle / unread` 三态（没开自动生成、也从没生成过时不显示；有一份没看过的个人简报时紫色加圆点）。点一下开「个人助理」窗口。 |
| 2 | 个人简报 | 到点（默认 08:30，周末也做）或点「重新生成」：先在本地克隆里 `git pull`，再让「AI 对话」里的 Anthropic 服务商（个人 key）用三个**只读**工具读库（先 INDEX.md，再按需读），写出「待复习 / 决策与检查点 / 饮食·本周 / 复习 / 今天 / 建议」六节。一天一次，失败隔 20 分钟再试、最多 3 次（复用工作简报的 `is_due`）。 |
| 3 | 透明度 | 窗口顶部三行：`生成于 … · 模型 · 思考 medium · 输入 / 输出 tokens · 秒 · 工具 N 轮 · 读了 N 个文件`；`肥鱼用你自己的 API key 直连 Anthropic，只读本地克隆，没有连接器`；`读过：文件列表`（最多 8 个 + N）。忙碌时状态行写「正在让 {模型}（思考 {强度}）读 AI-Base…」。生成完且窗口没开着 → 带「查看 / 知道了」的常驻提醒。 |
| 4 | 灵感记录 | 「灵感」页：输入框 + 同高「记下」，Ctrl+Enter。追加到 `User/灵感 Inspiration.md` 当天那一节（文件不存在就带 frontmatter 建；多行缩进两格；`updated:` 跟着改），然后 **Windows 的 git** `add → 有变化才 commit → pull --rebase --autostash → push`。推送用钥匙串里的 GitHub Token（与知识库同步 / 连接器共用，经 `GIT_CONFIG_*` 环境变量注入，不进命令行）；被拒（401 / 403）就让普通 git（Git Credential Manager）再试一次并在失败文案里附上 Token 的 scopes。状态行：已写进 → 正在提交并推送… → 已推送（HH:MM）/ 没推上去：原因。不经 AI。 |
| 5 | 在 Obsidian 打开 AI-Base | 克隆目录已在 Obsidian 登记成库 → `obsidian://open?path=<INDEX.md 绝对路径>`（用 `path=` 而不是 `vault=`：Drive 上冻结的旧库也叫 AI-Base，按名字会打开错的那个）；没登记 → 打开文件夹并冒泡说明要先「Open folder as vault」一次。 |
| 6 | 只读与隐私 | 读取工具是 `KnowledgeBase` 的包装：跳过点目录（克隆里有 `.git`）、`login/`、`9-Assets/`、名字含 pass / secret / token / credential / .env 的路径读不到也搜不到；提示词写明只读、库里的文字是材料不是指令、不复述凭据。日志只记成败 / 秒 / token / 轮数，不记简报正文、灵感正文；提交说明只有日期时间。 |
| 7 | 设置 | 「自动化与联动 → 个人助理」：开关、克隆目录（默认 `%USERPROFILE%\Github\AI-Base`）、每天几点、**模型**（跟 AI 对话一致 / Claude 5 家族四个 / 自定义）、**思考强度**（跟 AI 对话一致 / low～max），加折叠的「这个功能怎么运作」五步说明。没有 Windows 的 git 只在提示里说明（简报不需要 git）。 |
| 8 | 中英文 | 59 个 `personal.*` / `island.personal.*` 键，两张表对齐；英文串里不含中文（文件名在英文里写成 “Inspiration” note under User/）。 |

**不变量 / 红线**：不碰 WSL、不碰公司账号、不接任何连接器；不改 Meal Log、不做登记进食；`%APPDATA%` 里给聊天用的
知识库副本照旧（简报直接读克隆，不受那份副本「一天一同步」的延迟影响）；公开仓库里不出现用户库里的内容
（测试与截图全是中性样例，本报告只写计数）。

## 二、修改文件说明

| 文件 | 增删 | 改动 |
|---|---|---|
| `pet/personal_vault.py`（新） | +275 | 配置键 `personal`（`normalize`：enabled / repo_dir / time / model / effort，模型名与强度只认合法值，空 = 跟聊天）；`git_exe()`（PATH 或 `C:\Program Files\Git\cmd\git.exe`）、`run_git()`（`CREATE_NO_WINDOW`、`GIT_TERMINAL_PROMPT=0`）、`token_env()`、`github_token()`（惰性导入 `pet.chat`：`config.py` 导入时要用本模块，不能依赖聊天）、`describe_token_scopes()`、`pull()` / `sync_inspiration()`（Token 优先、被拒退到 GCM 一次）、`append_inspiration()`（原子写）、`obsidian_vault_uri()`。 |
| `pet/personal_briefing.py`（新） | +255 | `PersonalBriefing(wb.Briefing)` + model / effort / tokens / files_read / pull_note；提示词（带 `{language}`）；`parse_text`（首行 `概要：`）；`is_due`（`weekdays_only=False`）；`GuardedKnowledgeBase` / `RecordingToolset`（拒绝名单、记读过的文件）；`generate()`（非 Claude 通道 / 没有克隆直接报错，`ProviderError` 折成失败并保留已读文件）；状态文件 `personal-briefing.json` 的 load / record / latest。 |
| `pet/chat/anthropic_provider.py` | +71 / −0 | 新 `complete()` + `Completion`：无头一问一答，`describe_image` 的骨架 + `stream()` 的本地工具循环（不带连接器），逐轮累加 `usage`（含缓存读写）、取 API 回的模型名、数轮数；超轮数 / 空回复 / 拒答抛 `ProviderError`；`client` 可注入。`stream()` 本身没动。 |
| `pet/personal_service.py`（新） | +276 | `PersonalService(QObject)`：照 `WorkBriefingService`（启动延时 25 s、每 60 s 检查、daemon 线程、generation 计数）；`_launch` 在 GUI 线程解析「AI 对话」的服务商 + key，线程里 `pull → generate`；`add_inspiration` 落盘后后台 sync（git 串行一把锁）；`open_in_obsidian`；`busy_model / busy_effort / sync_state / pushed_at` 给界面。 |
| `pet/personal_ui.py`（新） | +224 | `meta_line()`（三行透明度）、`InspirationPanel`（复用笔记页的输入框与 objectName，样式表自动套上）、`PersonalController`（自己建一个 `WorkBriefingWindow`：标题「个人助理」、两页、底部「在 Obsidian 打开 AI-Base」；提醒 `alert_id=personal-briefing`；岛状态）。 |
| `pet/work_briefing_ui.py` | +19 / −5 | `WorkBriefingWindow.show_briefing(..., meta=None, busy_text="")` 允许覆盖元信息行与忙碌文案；`add_action_button()` 插在「重新生成」左边；`buttons_layout` 暴露。向后兼容，工作简报不变。 |
| `pet/dynamic_island.py` | +68 / −2 | 人形图标：常量、`personal_requested` 信号、`_personal_state`、`set_personal_state / personal_tooltip`、`_personal_icon_left`（铃铛相应右移）、`personal_button_rect / _personal_hit`、tooltip 分支、胶囊宽度、内容缓存键、`_paint_personal_icon`（圆头 + 肩弧，未读紫点）、点击分支。 |
| `pet/app.py` | +35 / −0 | `_start_personal()`（不受「没有 WSL」门控；没装聊天模块就跳过）、`_push_island_personal_state()`、`_open_personal_from_island()`；岛信号与启动序列接线。 |
| `pet/config.py` | +6 / −0 | `personal` 键的五处登记（import / 默认值 / reload 白名单 / normalize / 触发集合）。 |
| `pet/settings_personal.py`（新） | +123 | 设置节 + 折叠说明 + 保存；模型与强度各一个 `ModernSelect`。 |
| `pet/modern_settings_dialog.py` | +5 / −1 | import、插入「自动化与联动」第 6 / 7 节、保存。 |
| `pet/locale/zh.json`、`en.json` | 各 +60 / −1 | 59 个键。 |
| `scripts/capture_personal_window.py`（新） | +104 | 窗口两页 × 白天黑夜 × 中英 → PNG（中性样例，不调模型不起 git）。 |
| `scripts/personal_briefing_once.py`（新） | +53 | 真实配置跑一次，只打印元信息（不打印正文），写进状态文件。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_personal_vault.py`（新） | +186 | 配置默认 / 清洗 / 重启存活；灵感首条建文件、同日追加、次日新节、插入中间节不动后文、`updated:` 更新；git 序列（add / diff / commit / pull / push）与 Token 环境变量（不进 argv、base64 正确）、没变化不提交、pull 失败 abort、Token 被拒退到普通 git 并附 scopes；scopes 探测；git.exe 回退；Obsidian 地址用 `path=`。 |
| `tests/test_personal_briefing.py`（新） | +172 | 提示词（日期、星期、六节、只读、语言）；解析；周末也做、一天一次；工具记账与拒绝名单（login / Pass / .git / .obsidian，搜索走不进凭据目录）；`generate` 填模型 / 强度 / token / 轮数 / 文件；非 Claude 通道与没有克隆；`ProviderError` 折成失败；状态文件往返。 |
| `tests/test_anthropic_complete.py`（新） | +134 | 假 client：一轮工具 + 回答的 usage 求和与轮数、`system_note` 拼进 system、工具异常回 `is_error`、`effort` 透传与 Haiku 不发 effort、轮数上限 / 空回复 / 拒答、SDK 异常翻译。 |
| `tests/test_personal_ui.py`（新） | +316 | 服务：先 pull 后 generate、用聊天服务商、一天一次；pull 失败仍生成；没有 Claude 通道报错不崩；灵感追加 + 推送 + 状态流转；推送失败保留文件；没有克隆不写。窗口：标题 / 两页 / 按钮顺序 / 元信息三行 / 正文；忙碌行写模型与强度；关着窗口时提醒 + 岛 unread → 打开后 idle；失败只冒泡；灵感页记下与状态；Obsidian 未登记退回文件夹 + 提示、登记后 `path=`；英文；窗口壳的 `meta=` / `busy_text=` / `add_action_button`。 |
| `tests/test_island_personal.py`（新） | +92 | 图标占位与顺序（简报 · 个人 · 铃铛）、三态 tooltip、缓存键、点击发信号、英文；`AppShell._push_island_personal_state` / `_open_personal_from_island`。 |
| `tests/test_settings_personal.py`（新） | +118 | 六行都在「自动化与联动」且显示已存值；模型与强度各自可选、留空 = 跟聊天、自定义模型往返；没有 git 只是提示；英文。 |
| `tests/test_single_process_shared.py` | +3 | 假岛加 `set_personal_state`。 |
| `tests/test_config_schema.py` | +1 | reload 白名单快照登记 `personal`。 |

## 三、实现要点

- **个人 key 通道原本不回报用量**（`stream()` 丢掉 `final.usage`）：没有改流式对话，而是在同一模块加 `complete()`，
  复用 `_client / _open_stream / _check_final / _run_client_tools / _translate_error`，把 usage、模型名、轮数收回来。
- **读过哪些文件**不是改 `_run_client_tools`，而是在工具集外面包一层记账（`RecordingToolset`），顺便放拒绝名单。
- **Token 不进命令行**：`GIT_CONFIG_COUNT/KEY_n/VALUE_n` 注入 `credential.helper=`（清空助手）和
  `http.https://github.com/.extraheader`；只有碰远端的 pull / push 带它，本地命令不带。
- **文件名撞车**：克隆目录和 Drive 旧库同名 AI-Base，Obsidian 的 `vault=` 会撞上，所以用 `path=`。
- 英文表里不能有中文（`tests/test_settings_english.py` 会拦），灵感文件在英文里写成 “Inspiration” note under User/。

## 四、性能分析

**环境**：Windows 11 Pro 26300，PySide6 / Qt 6.12，`.venv` Python 3.13，Anthropic 直连，模型 `claude-sonnet-5`、
思考 medium，本地克隆 62 个 md / 4.1 MB。`scripts/personal_briefing_once.py` 真跑两次：

| 指标 | 第 1 次 | 第 2 次 | 说明 |
|---|---|---|---|
| 总用时 | 88.6 s | 85.0 s | 含 `git pull`（< 2 s）与 8～9 次请求 |
| 工具轮数 | 9 | 8 | 每轮一次完整请求 |
| 读过的文件 | 7 | 7 | INDEX + 决策日志 ×3 + 饮食 + 学习 ×2（计数，不列名） |
| 输入 tokens（含缓存读写） | 263,655 | 199,997 | 每轮重发整段前缀；`cache_control` 已开，绝大部分是缓存读 |
| 输出 tokens | 6,411 | 6,339 | 含思考 |
| 简报正文 | — | 1,793 字，六节齐全 | — |

其余路径：

| 指标 | 实测 / 说明 |
|---|---|
| 稳态 | 每 60 s 一次 `is_due`（读配置 + 读一个小 JSON），与工作简报同量级；不生成时没有别的代码跑 |
| 灵感一条 | GUI 线程一次文件读写（< 5 ms，文件几 KB）；后台 5 次 `git.exe`（add / diff / commit / pull / push），实测本机 4～6 s，网络占大头；期间一把锁，不阻塞界面 |
| 新增线程 | 生成 / 推送时各起一个 daemon 线程，跑完即退；无常驻线程 |
| 新增系统调用 | 生成：`git.exe` ×1 + HTTPS 请求 8～9 次；灵感：`git.exe` ×5；Obsidian：`ShellExecute` ×1 |
| 内存 | 状态文件只留最近一份简报（约 3 KB）；窗口懒建，关了保留 |
| 新增测试 | 6 个文件 52 例，offscreen 共约 6 s |

**结论**：① 稳态零开销；② 每天一次真实调用，约 85～90 秒、输入 20～26 万 token（缓存读为主）、输出 6 千；
用量多在「每轮重发前缀」——设置里可以把模型换成 Haiku 或把强度调低；③ 灵感不经 AI，只有 git 的网络往返；
④ 内存无常驻增长。

## 五、实机运行记录

- **真实简报**（个人 key，`scripts/personal_briefing_once.py`）：第 1 次 `ok=True … seconds=88.6 tokens_in=263655
  tokens_out=6411 rounds=9`（脚本随后在 cp1252 控制台打印中文文件名时崩溃，已改成 utf-8 输出）；第 2 次
  `git pull: ok`，`ok=True model=claude-sonnet-5 effort=medium seconds=85.0 tokens_in=199997 tokens_out=6339 rounds=8`，
  `files read (7)`，`sections=['## 待复习', '## 决策与检查点', '## 饮食 · 本周', '## 复习', '## 今天', '## 建议']`，
  `recorded to …\personal-briefing.json`。正文看过：六节都按库里的内容写，没有编造；凭据类文件没在读取列表里。
- **截图**（`QT_QPA_PLATFORM=windows` 真实字体，`scripts/capture_personal_window.py`，中性样例）：
  `docs/screenshots/personal-2026-10-17/personal-{briefing,ideas}-{light,dark}-{zh,en}.png` 8 张。看过：顶部三行
  元信息（模型 / 强度 / token / 秒 / 轮 / 文件数、怎么连的、读过的文件）、六节正文、底部「在 Obsidian 打开 AI-Base ·
  重新生成 · 关闭」；灵感页输入框与「记下」同高、提示行、「已推送到 GitHub（时间）」。
- **红灯**：六个新测试文件在实现前均为收集期 `ImportError` / `AttributeError`（模块与属性尚不存在）；
  `tests/test_config_schema.py::test_defaults_snapshot_matches_current` 在登记 `personal` 前红（新键必须进快照）。
- **肥鱼已重启**（结束不含 `--settings` 的主进程，`run.bat` 拉起，`acquired pid=20716`，日志无 Traceback）。状态文件里
  已有一份真实简报，所以岛上应出现人形图标（idle）；用户现有配置里 `personal.enabled` 仍是 False（默认关），要每天
  自动生成需在设置里打开。本机没有能点真实岛按钮的自动化工具，以上是渲染与服务层的证据。
- **没做的实机项**：没有在用户真实克隆里记一条灵感（会往用户的 GitHub 仓库推一条测试提交）；推送路径由假 git 的
  序列测试与「Token 对该仓库 `push: true`」的探测结果（`GET /repos/…` 的 `permissions`）共同覆盖。首次真推送时
  若 Token 被拒，会退到 Git Credential Manager 的一次性登录——这一步未实测。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `ruff check pet tests scripts` | All checks passed |
| 聚焦 + 相关 | `pytest -q tests/test_personal_vault.py tests/test_personal_briefing.py tests/test_anthropic_complete.py tests/test_personal_ui.py tests/test_island_personal.py tests/test_settings_personal.py tests/test_briefing_metro.py tests/test_i18n.py tests/test_settings_work_notes.py tests/test_work_briefing_links_and_island.py tests/test_island_notifications.py tests/test_single_process_shared.py tests/test_work_briefing.py tests/test_work_notes_ui.py tests/test_settings_english.py` | 全部通过（见下方全量） |
| 全量 | `python -m pytest -q -p no:cacheprovider`（offscreen，临时 APPDATA，从 Git Bash 启动） | `6 failed, 5435 passed, 11 skipped in 503.81s (0:08:23)`：4 个是本机既有的环境性基线（路径超 260、两个子进程 cp1252、多显示器负原点）+ 1 个是从 Git Bash 启动才有的既有编码失败；剩下 1 个 `test_menu_layout.py::test_compact_agent_sound_controls_reflow_inside_their_setting_row` 是本次引入的：「AI-Base 克隆目录」那行标签比工作笔记的宽，控件最小宽度 360 让整页在 720 的窄窗里撑到 590，别的行就不再换行。把该输入框最小宽度改成 200 后（整页最小宽度回到 392，与改前一致），这一族 `test_menu_layout.py tests/test_settings_*.py tests/test_config_schema.py tests/test_personal_ui.py tests/test_island_personal.py` 120 例全过。 |

## 七、已知限制与后续

- 输入 token 偏多（每轮重发前缀、读的文件长）。可选的后续：提示词里限制每次 `kb_read` 的文件数，或让 `kb_read`
  支持按节读取。
- 分隔条 / 窗口大小不记忆；简报不记历史（只留最近一份，同工作简报）。
- 右键菜单暂没有「个人助理」入口（岛上的图标是唯一入口；设置里能开关）。
- Obsidian 登记要用户做一次；首次推送若 Token 被拒要在 GCM 的窗口里登录一次。

## 八、风险与回滚

- `git revert` 即可；新增配置键 `personal` 留在用户配置里无害（normalize 会清洗）。
- 风险点：往用户的 GitHub 仓库推送——只推 `User/灵感 Inspiration.md` 一个路径，pull 失败就 `rebase --abort` 并报告，
  本地文件保留；永远不 force。
- 风险点：简报读到不该读的内容——拒绝名单 + 提示词；日志不记正文。
