# PR 报告：设置窗口英文化——大多数设置项跟随「界面语言」

> **基线**：`5ecd1a4`（feat(work-notes): 流程说明改成设置页折叠节；「工作笔记」菜单入口上提到 Agent 联动；笔记可删）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-16
> **范围**：36 个文件（实现 22、语言表 2、测试 1、脚本 1、文档 1、截图 9 张）
> **关联**：[`PR-REPORT-UI-LANGUAGE-ISLAND-2026-10-14.md`](PR-REPORT-UI-LANGUAGE-ISLAND-2026-10-14.md)（i18n 第一片：灵动岛）；
> [`PR-REPORT-BRIEFING-METRO-2026-10-15.md`](PR-REPORT-BRIEFING-METRO-2026-10-15.md)（简报 / 笔记窗口已是中英文）

## 一、核心特性

用户 2026-10-16：「我们继续翻译，请这次翻译设置里的大多数选项吧」。设置窗口（侧栏 9 个能力域及其全部页面，
含 AI 与对话、语音报时、节日提醒、菜单编排编辑器）的界面文字全部进了 `pet/locale`，界面语言选 English 时
整窗英文。

**量化**：英文界面下设置窗口里可见的、仍含中文的文字（侧栏、页 / 节标题、行标题与提示、按钮、下拉项、占位，去重）：

| | 条数 |
|---|---|
| 改动前（HEAD 的临时 worktree 实测） | 686 |
| 改动后 | 13（全部有意保留，见下） |

有意保留的 13 条：语言那一行的中英双语标题（`Language (界面语言)` / `Language / 语言`）、语言下拉里的「中文」
（语言选择器按惯例显示语言自称）、自定义中文台词框里的中文示例诗句、9 个内置对话背景主题名（夏沫琉璃、
赛博夜城……内容名，不是界面文字）。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 自动改写 | 抽取脚本按 AST 找出设置相关 17 个模块里所有运行时求值的中文字面量（排除 docstring、日志），按文件去重后 ~660 条；人工逐条翻成英文；改写脚本把每处换成 `t("settings.<模块>.<英文前几个词>")`，f-string 换成带命名参数的 `t("键", 名=表达式)`，同时写进中英两张表；校验两边 `{占位符}` 与 `%` 说明符一致。 |
| 2 | 导入时求值的表（93 条） | 模块级常量改存文案键、用到的地方再 `t()`（Slack 关注 / 通知中心 / 托盘 / 语言 / VS Code / 保存按钮 / 肥鱼控件的提示）；事件名表 `DIALOGUE_LABELS`、模板参数表 `DIALOGUE_PARAMS`、侧栏 `SETTINGS_DOMAIN_NAV` 保持中文（测试与深链接按它认），显示时经 `dialogue_label` / `dialogue_param` / `domain_label` 翻译。 |
| 3 | 别的模块提供的选项 | 报时频率、36 个音色说明、节日提醒方式、5 个气泡方案、知识库状态一句、快捷启动里的「默认浏览器」、对话窗口两种风格名：数据表的中文不动，设置页显示时按 id 取文案键。 |
| 4 | 深链接 | `select_page` 中文域名、英文域名都认（`select_page("自动化与联动")` 在英文窗里也能跳）。 |
| 5 | 英文更长的地方 | 「Choose…」「Preview」两类按钮从定宽改成最小宽度；侧栏 `Automation and linking` 放不下 200px，英文叫 `Automation`。 |
| 6 | `i18n.maybe_t` | 「是表里的键就翻译、否则原样返回」：文件对话框过滤器默认值改成键，调用方仍可传自己的过滤器文字。 |

**红线 / 不变量**：中文界面逐字不变（zh 表的值就是原来的字面量，46 个设置相关测试文件、946 个用例不改一行即过）；
配置里存的值不变（下拉的取值、彩蛋标题默认值「厉害了我的鲸 / 请点击」都不翻——后者会被存进配置并显示在右键菜单里）；
侧栏域名的中文仍是内部标识。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动 |
|---|---|---|
| `pet/modern_settings_dialog.py` | +257 / −314 | 336 处字面量改 `t()`；事件名 / 模板参数两张表拆出去（见下行）并从那里再导入；侧栏建页用 `domain_label`；`select_page` 中英都认。 |
| `pet/settings_dialogue_text.py`（新） | +87 / −0 | `DIALOGUE_LABELS` / `DIALOGUE_PARAMS`（中文原文，键是内部标识）+ `dialogue_label` / `dialogue_param`。从主文件拆出：加翻译辅助函数让主文件超了行数预算（2308 > 2291），按预算测试的指引拆而不是调预算，拆完 2234 行。 |
| `pet/settings_widgets.py` | +66 / −36 | 35 处改 `t()`；`SETTINGS_DOMAIN_KEYS` + `domain_label`；`IMAGE_NAME_FILTER` / `AUDIO_NAME_FILTER` 改存键、`ResourcePathPicker` 建控件时 `maybe_t` 翻好（`name_filter` 属性仍是可读的过滤器文字）；「Choose…」按钮最小宽度；快捷启动「默认浏览器」显示名 `_quick_launch_display_name`。 |
| `pet/settings_pet_controls.py` | +59 / −64 | 51 处改 `t()`；直播捕获 / 省电模式 / 「对所有肥鱼生效」常量改存键、函数里 `t()`；气泡方案显示名；两个「Preview」按钮最小宽度。 |
| `pet/settings_menu_layout_editor.py` | +48 / −47 | 51 处改 `t()`；图标文件对话框过滤器 `t()`。 |
| `pet/settings_interaction.py` | +39 / −41 | 45 处改 `t()`；页签名 `TAB_LABELS` 改存键。 |
| `pet/chat/ai_settings_page.py` | +87 / −81 | 97 处改 `t()`；`chat_style_label`（对话窗口风格名）。 |
| `pet/chat/knowledge_base.py` | +4 / −3 | `describe()` 三句状态走 `t()`。 |
| `pet/voice_chime_settings.py` | +31 / −31 | 34 处改 `t()`；报时频率、音色说明显示名按 id 取键。 |
| `pet/festival_settings.py` | +35 / −49 | 33 处改 `t()`；提醒方式显示名按 id 取键。 |
| `pet/settings_slack_watch.py` | +21 / −18 | 10 处改 `t()`；模型下拉显示名、5 个提示常量改存键。 |
| `pet/settings_vscode.py`、`settings_notifications.py`、`settings_tray.py`、`settings_language.py`、`settings_save.py`、`settings_file_interpret.py`、`settings_music.py`、`settings_standalone.py` | 各 +2～+14 | 字面量改 `t()`、提示常量改存键；语言那一行的提示改口（「大部分界面跟着换」）。 |
| `pet/i18n.py` | +9 / −0 | `maybe_t`。 |
| `pet/locale/zh.json`、`pet/locale/en.json` | 各 +798 / −1 | 797 个 `settings.*` 键（zh 值 = 原字面量）。 |
| `scripts/capture_settings_pages.py` | +5 / −1 | `--language zh|en`。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_settings_english.py` | +196 / −0 | 英文窗里没有中文（只剩有意保留的）、侧栏英文、标题英文；中文窗不变；`select_page` 中英都认；行标题 / 提示 / 保存按钮 / 6 类下拉项英文；**没有按钮被定宽截断**；英文搜索；导入时求值的表跟随语言（事件名、模板参数、域名、过滤器、`maybe_t` 原样返回、直播捕获提示）；797 个键中英占位符一致。 |

### 未改动（看起来相关但不在这次范围）

- **右键菜单本身的条目名**（registry `ACTION_LABELS` 等）：菜单编排编辑器里列出的「护驾 / AI 对话……」是菜单系统的文案，
  属于另一个界面，单独做。
- `pet/chat/settings_dialog.py`：旧版拓扑的独立「AI 设置」对话框，overlay 下不用。
- 托盘菜单、聊天窗、气泡与自言自语的内容文案、角色名、对话背景主题名。
- 运行中的错误提示里由别的模块拼的中文（如同步失败原因 `state.error`）。

## 三、实现要点

- **键名从英文自动生成**：`settings.<模块前缀>.<英文前 5 个实词>`，同前缀内去重（加 `_2`）。750 个手起的键名不现实，
  从英文派生既可读又稳定。
- **字节级改写**：源文件是 CRLF，AST 的列号是 UTF-8 字节偏移——第一版用文本读取（换行被规范成 LF）算偏移，改写时
  在 CRLF 字节流上错位，`UnicodeDecodeError` 当场暴露；改成按原始字节解码后重抽，ID 不变（清单文件哈希一致）。
- **嵌套**：f-string 表达式里的中文（`{proc or '（未知）'}`）折进外层调用的参数表达式里一并改写，避免区间重叠。
- **导入时求值**：设置进程是先建 Config（定语言）再惰性导入设置模块，模块级 `t()` 在生产上碰巧也对；但测试与其他进程
  不保证这个顺序，所以一律「常量存键、用时翻译」。
- **不翻的字面量**：会被存进配置的内容默认值（彩蛋标题）在译文里标 `null`，改写脚本跳过；字典键形式的侧栏域名（DICTKEY）跳过。

## 四、性能分析

`t()` 是一次字典查表（表在首次使用时读入并缓存）。设置窗口建一次大约多 800 次 `t()` 调用。

| 指标 | 实测 | 归属 |
|---|---|---|
| 语言表大小 | zh 958 键、en 966 键；两个 JSON 文件各约 90 KB | 进程内各读一次、缓存 |
| `t()` 单次 | 字典查找 + 无参数时不格式化（微秒级） | 建设置窗口时 ~800 次 |
| 设置窗口建窗 | 设置相关 46 个测试文件跑完用时与改动前同量级（136 s，946 例） | 打开设置时 1 次 |

**结论**：① 稳态零开销（只在建窗口时查表）；② 新增路径是建窗时的 ~800 次字典查找，相对 Qt 建控件可以忽略到测不出——
没有单独计时；③ 无新系统调用 / 网络 / 线程，多读两个 JSON（已有机制）；④ 内存：两张表多 ~800 个短字符串。

## 五、实机运行记录

- **改动前的现场**（HEAD 临时 worktree，英文界面）：`686 visible texts still contain Chinese`，侧栏
  `['常规', '肥鱼', '互动', '菜单', '桌面组件', 'AI 与对话', '自动化与联动', '语音', '文件识别']`。
- **改动后**：侧栏 `['General', 'Fish', 'Interaction', 'Menu', 'Desktop widgets', 'AI and chat', 'Automation', 'Voice',
  'File recognition']`，剩 13 条有意保留的中文（见一）。
- **红灯**：把新测试拷进 HEAD worktree 跑：`6 failed, 1 passed`（通过的那条是「中文界面不受影响」，本就该过）。
- **截图**（`QT_QPA_PLATFORM=windows` 真实字体，`scripts/capture_settings_pages.py --language en`）：
  `docs/screenshots/settings-english-2026-10-16/` 9 页，逐页看过；第一轮截图发现两处问题——侧栏
  「Automation and…」被截、「Choose…」被截成「hoose」、「Preview」被截成「Previe」——修完重抓。同一脚本的 `--dark` 在当前
  主题逻辑下抓出来和浅色逐字节相同，不算证据，已删。
- 设置窗口是独立进程，用户的配置里界面语言已是 English，下次打开设置即是英文；本机没有能点真实窗口的自动化工具，
  以上是渲染证据。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 红灯 | 新测试在 HEAD worktree | 6 failed, 1 passed |
| 静态检查 | `ruff check pet tests scripts` | All checks passed |
| 聚焦 | `pytest -q tests/test_settings_english.py` | 8 通过 |
| 设置相关族 | 名字含 settings / menu_layout / festival / voice / i18n / stream_capture / overlay_copy / github_connector / knowledge_base / about_user / youtube / work_notes / briefing / slack / interaction / tray_icon_custom / notification / vscode / dialogue / persona 的 46 个文件 | 946 通过 |
| 全量 | `python -m pytest -q -p no:cacheprovider`（offscreen，临时 APPDATA） | 最终状态：`4 failed, 5369 passed, 11 skipped in 510.28s (0:08:30)`，4 个失败全是本机既有的环境性基线（路径超 260；两个子进程输出按 cp1252 解码；多显示器负原点）。第一轮全量另有 2 个本次引入的失败，已修，见文末。 |

## 七、已知限制与后续

- 右键菜单、托盘菜单、聊天窗还没翻；它们是下一片。
- 换语言后已经开着的设置窗口不会就地刷新，重开生效（和简报窗口一致）。
- 新增设置项时文案要直接写 `t("settings.…")` 并在两张表里各加一条；`test_settings_english` 的「英文窗里没有中文」会拦住漏网的。

## 八、风险与回滚

- 纯界面文案；`git revert` 即可，无配置迁移。语言表多出的键对旧版本无影响。
- 风险点：被改写成 `t()` 的字面量若在别处被当作值比较，英文下会对不上——审计时没有发现中文参与比较（`COMPARE` 为 0），
  唯一的按文字查找（`old_pages.get(...)`）两端都改成了同一个键。

## 第一轮全量抓到的两处（已修）

第一次全量（改写完成后）除 4 个既有基线外多出两个失败，都是本次引入的：

- `test_architecture::test_modern_settings_dialog_py_line_budget`：主文件 2308 行 > 预算 2291。加的 `dialogue_label` /
  `dialogue_param` / `import re` 让它涨了 17 行。按预算测试自己的指引「优先拆出」，把两张表和辅助函数挪到新模块
  `pet/settings_dialogue_text.py`，主文件降到 2234 行；`DIALOGUE_PARAMS` 等名字从主文件照样能导入（测试按这个路径取）。
- `test_desktop_pet_features::test_easter_egg_path_and_color_controls_use_native_pickers`：断言
  `"*.webp" in picker.name_filter`，而过滤器常量改成了键。改成 `ResourcePathPicker` 构建时就 `maybe_t` 翻好，属性里存的
  是可读的过滤器文字，测试原样通过。
