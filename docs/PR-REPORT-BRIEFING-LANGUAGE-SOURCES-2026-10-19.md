# PR 报告：工作简报 / 工作笔记跟界面语言出英文；简报来源可配置（邮件 / Slack / Jira / GitHub PR / 日历 / 建议）并加「这个功能怎么运作」

> **基线**：`0b903c2`（feat(i18n): 内置表达风格加英文版）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-19
> **范围**：12 个文件（实现 4 改 + 1 新、语言表 2、测试 2 新 + 4 改、脚本 1 新）+ 本报告 + 2 张截图
> **关联**：[`PR-REPORT-WORK-BRIEFING-2026-10-12.md`](PR-REPORT-WORK-BRIEFING-2026-10-12.md)（简报本体）、
> [`PR-REPORT-WORK-NOTES-SETTINGS-2026-10-15.md`](PR-REPORT-WORK-NOTES-SETTINGS-2026-10-15.md)（笔记的设置节与流程说明）

## 一、核心特性

用户 2026-10-19：「setting language is english, the generated briefing and notes are chinese. please update it; also for briefing and
notes we need a button or folder section to explain how it works, i.e. how, when, what, how it sends to claude; and if possible make it
configurable, e.g. include email, slack, jira, github, PR, calendar, suggestion」。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 简报跟界面语言 | 提示词分中英两套整段模板（不是只在中文提示词里加一句「用英文写」）：英文版要求 `Summary:` 开头、`## Jira / PR / Slack / Calendar / Email / Do first` 小节、空节写 None。`parse_output` 同时认 `概要：` 与 `Summary:`（含加粗写法）；兜底概要与错误文案走 `t()`。 |
| 2 | 笔记跟界面语言 | `work_notes.build_prompt` 按界面语言选整套模板（英文版同一份 JSON 契约：title / summary / details / remind_at / reason / tags）。总结失败的五条文案走 `t()`。已有的笔记不会自动变——点「重新总结」才会拿到英文。 |
| 3 | 来源可配置 | 新配置 `work_briefing.sources`：`jira / pr / slack / calendar / email / suggestions`（邮件默认关，其余默认开）。开关决定：提示词里列哪些来源（编号重排）、输出哪几节、放行给 Claude Code 哪些只读工具、要不要先在 WSL 里跑 gh（PR 关着就不跑）。邮件开着才放行 Gmail 的 `search_threads / get_thread / get_message`，标签 / 草稿 / 发送 / 删除 24 个工具按名字拒绝；关着时整个 Gmail 连接器照旧拒绝。 |
| 4 | 设置节「工作简报」 | 新 `pet/settings_work_briefing.py`：工作日自动生成（没有 WSL 置灰并说明）、只在工作日、几点生成、用哪个模型（Sonnet / Haiku / Opus / 自定义）、六个来源开关（每个开关的提示写明读什么、放行哪个连接器）。放在「自动化与联动」最前面、工作笔记之上。 |
| 5 | 「这个功能怎么运作」 | 简报一节后紧跟默认收起的说明：什么时候做（每分钟检查、一天一次、失败重试）、先做什么（gh 代查 PR）、发给 Claude 什么（提示词里有哪些内容）、它能用什么（无界面的 Claude Code、不给内置工具、只给勾选来源的只读连接器、写工具按名字拒绝）、结果放哪、不会做什么。工作笔记已有的说明节补了一段「发给 Claude 什么」。 |

**不变量**：中文提示词的内容与改前一致（测试逐句钉住：JQL、`<pr_list>`、星期、72 / 24 小时、只读、五节顺序）；右键菜单里
的开关与定时照旧，和设置节写同一个配置键；`is_due` / 状态文件不变。

## 二、修改文件说明

| 文件 | 增删 | 改动 |
|---|---|---|
| `pet/work_briefing.py` | +162 / −61 | 工具表按来源分组（`_READ_TOOLS_BY_SOURCE`）、Gmail 读 / 写工具名单；`SOURCES` / `DEFAULT_SOURCES` / `normalize_sources`，`normalize` 多一键 `sources`；`allowed_tools(sources)` / `denied_tools(sources)` / `claude_command(model, sources)`；`_PROMPTS` 中英两套片段 + `build_prompt(now, prs, sources, language)` 按开关拼装；`SUMMARY_PREFIXES`；`generate(..., sources=)` PR 关着不跑 gh；错误与兜底概要走 `t()`。 |
| `pet/work_briefing_service.py` | +3 / −2 | `_launch` 把 `settings["sources"]` 传给 `generate`。 |
| `pet/work_notes.py` | +34 / −8 | `_PROMPT_EN` + `_PROMPTS`，`build_prompt(note, now, language=None)` 按界面语言选模板；`parse_summary` / `summarize` 的五条错误走 `t()`。 |
| `pet/settings_work_briefing.py`（新） | +113 | 设置节的行、流程说明节（复用 `settings_help.help_section`）、保存。 |
| `pet/modern_settings_dialog.py` | +12 / −5 | import；「自动化与联动」插入「工作简报」节 + 说明节（索引 4 / 5，其后各节后移）；保存。 |
| `pet/locale/zh.json`、`en.json` | 各 +42 / −2 | `briefing.settings.*`（28 键）、`briefing.error.*` / `briefing.fallback_summary`（6）、`notes.error.*`（7）；`notes.settings.flow_tooltip` 补一段。 |
| `scripts/capture_work_briefing_settings.py`（新） | +64 | 设置节 + 展开的说明渲染成 PNG。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_work_briefing_sources.py`（新） | +117 | 英文提示词的开头、星期 / 回看小时、英文小节与 `Summary:`、不含中文与邮件；中文提示词与改前逐句一致；`Summary:` / `**Summary:**` / `概要：` 都认，无概要行时英文兜底，英文错误；笔记提示词整套随语言切换，英文错误；来源归一化（邮件默认关、脏值）；关掉的来源从提示词与工具名单消失；邮件只在开着时放行三个读工具、写工具按名字拒绝、整连接器不再拒；`generate` PR 关着不跑 gh、邮件开着命令里有 Gmail 工具。 |
| `tests/test_settings_work_briefing.py`（新） | +101 | 全部行在「自动化与联动」且显示已存值；说明节含什么时候 / 发给 Claude 什么 / 它能用什么 / 结果放哪 / 只读 / gh / 不会，默认收起；保存写回全部字段含 `sources`，开了邮件后 `allowed_tools` 含 Gmail；没有 WSL 置灰；英文。 |
| `tests/test_work_briefing.py` | +7 / −6 | 配置形状断言加 `sources`；`generate` 假函数收 `**_kw`。 |
| `tests/test_briefing_metro.py`、`tests/test_work_notes_ui.py` | +5 / −3 | 假函数收 `**_kw`；英文提示词的断言改成整套英文模板。 |

## 三、实现要点

- 提示词按语言整套切换而不是插一句：模型对「周围全是中文、只有一句要求英文」的指令遵从不稳（用户看到的就是中文），
  整套英文模板连小节名、空节写法一起定下来，解析端同时认两种概要前缀。
- 来源开关是**三件事一起变**：提示词、输出小节、工具名单。少一件就会出现「提示词让它读邮件但工具没放行」或「放行了工具但没让它用」。
- 邮件的写工具名单按 claude.ai Gmail 连接器的工具名逐个列出（发送 / 回复 / 转发 / 草稿 / 垃圾箱 / 标签 / 敏感标签 / 垃圾邮件标记），
  插件版前缀也一并写上；关着时仍整个连接器拒绝，和改前一致。

## 四、性能分析

| 指标 | 实测 / 说明 |
|---|---|
| 一次真实英文简报（默认来源，WSL 公司账号，sonnet） | 88.8 s，14 轮工具调用，正文 10,030 字符，5 节齐全，正文 0 个中文字符 |
| 改前中文简报（2026-10-12 报告） | ~40～90 s 同量级 |
| PR 关着 | 少一次 `wsl.exe` + `gh search`（实测约 2～5 s） |
| 提示词长度 | zh 约 1,050 字 → 按来源拼装后默认同长；en 约 1,500 字符 |
| 设置窗口 | 多一节 11 行 + 一节说明；`tests/test_settings_work_briefing.py` 4 例建 4 次窗口共 ~2 s（offscreen） |
| 稳态 | 零：定时检查逻辑不变 |

**结论**：① 稳态零开销；② 每次生成的成本由勾选的来源决定，关来源就少工具调用；③ 无新系统调用 / 线程；④ 内存：语言表 +41 键。

## 五、实机运行记录

- **真实英文简报**（`i18n.set_language("en")` 后 `wb.generate(now, "sonnet", sources=DEFAULT_SOURCES)`，经 WSL 公司账号）：
  `ok True seconds 88.8 turns 14 denied []`，`headings ['## Jira', '## PR', '## Slack', '## Calendar', '## Do first']`，
  `chinese chars in output: 0`，概要 31 字符。只打印了元信息，正文没有进本报告（公司内容）。
- **截图**（`QT_QPA_PLATFORM=windows` 真实字体，`scripts/capture_work_briefing_settings.py`）：
  `docs/screenshots/work-briefing-settings-2026-10-19/work-briefing-settings-{zh,en}.png`：「工作简报」一节（五行设置 + 六个来源开关，
  邮件默认关）与展开的「这个功能怎么运作」六段。
- **红灯**：`tests/test_work_briefing_sources.py`、`tests/test_settings_work_briefing.py` 在改动前——没有 `sources`、没有英文模板、
  没有设置节——全部失败；改后绿。`test_switched_off_sources_leave_the_prompt_and_the_tool_list` 第一版红是因为链接规则里写死了
  「建议先做」四个字，改成「末尾的建议」后绿。
- 肥鱼已重启（`acquired pid=27120`，日志无 Traceback）；用户配置里界面语言是 English，下一次自动或手动生成的简报即为英文；
  已有的笔记要点「重新总结」才会换成英文。设置窗口是独立进程，下次打开即有新节。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `ruff check pet tests scripts` | All checks passed |
| 聚焦 | `pytest -q tests/test_work_briefing_sources.py tests/test_settings_work_briefing.py tests/test_work_briefing.py` | 59 通过 |
| 相关族 | `pytest -q` 上述 + `tests/test_work_notes.py tests/test_work_notes_ui.py tests/test_briefing_metro.py tests/test_work_briefing_links_and_island.py tests/test_settings_work_notes.py tests/test_settings_personal.py tests/test_settings_english.py tests/test_i18n.py tests/test_menu_layout.py tests/test_config_schema.py tests/test_desktop_pet_features.py` | 342 通过，1 失败 = 既有基线（图片目录选择器路径超 260） |
| 全量 | 未跑 | 改动限于简报 / 笔记的提示词、一个配置子键（normalize 兼容旧值）、一个设置节；运行时定时与生命周期不变；按 AGENTS.md 的「局部展示 token」豁免。 |

## 七、已知限制与后续

- Gmail 工具名按 claude.ai 连接器当前的命名写的；公司账号若没挂 Gmail 连接器，开了邮件也只会在那一节写「读不到」。
- 来源开关只在设置页；右键菜单里仍只有开关与定时。
- 已生成的简报 / 笔记不会重译。

## 八、风险与回滚

- `git revert` 即可；`sources` 子键留在配置里无害（normalize 会清洗）。
- 风险点：放行了邮件读工具——只读三件、写工具逐名拒绝；提示词写明不读推广与通知类邮件正文。
