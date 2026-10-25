# PR 报告：右键菜单英文化（含会话小鱼菜单与托盘菜单）

> **基线**：`29c02e4`（feat(i18n): 设置窗口英文化——大多数设置项跟随「界面语言」）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-16
> **范围**：22 个文件（实现 15、语言表 2、测试 1、脚本 1、文档 1、截图 2 张）
> **关联**：[`PR-REPORT-SETTINGS-ENGLISH-2026-10-16.md`](PR-REPORT-SETTINGS-ENGLISH-2026-10-16.md)（同一套抽取 / 改写脚本思路）

## 一、核心特性

用户 2026-10-16：「go ahead for the 右键菜单」。肥鱼的右键菜单（新版 / 旧版两种模板、全部子菜单与置灰提示）、
会话小鱼的右键菜单与它的详情卡文字、托盘菜单（和右键菜单同一套条目名，顺手一起）跟随「界面语言」。

**量化**：英文界面下右键菜单里仍含中文的条目（递归所有子菜单，含提示）：

| | 新版模板 | 旧版模板 |
|---|---|---|
| 改动前（HEAD 临时 worktree 实测） | 72 | 64 |
| 改动后 | 1 | 0 |

剩下那 1 条是彩蛋那一行的标题「厉害了我的鲸」（以及它右边的「请点击」）：那是配置里的内容，默认值是这个项目的
吉祥物梗名，可在 设置 → 菜单 → 彩蛋入口 里改成任何文字，不当界面文案翻译。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 自动改写 | 11 个菜单相关模块里运行时求值的中文（136 处，去重 131 条）译成英文，改写成 `t("menu.<模块>.<英文前几个词>")`。 |
| 2 | 导入时求值的表 | `ACTION_LABELS`（动作名，编辑器与菜单共用）、`CUSTOM_ICON_CHOICES`（图标选项）、语音报时 / 节日提醒开关的两组标签、置灰原因：表里的中文保持原样（内部标识 / zh 原文），`MENU_ACTIONS.label()` / `disabled_reason()` / `icon_choice_label()` 显示时翻译。`MenuActionRegistry()` 在导入时就实例化，所以它 `__init__` 里的置灰原因改写成**键名字符串**、由 `disabled_reason()` 经 `maybe_t` 翻译，而不是在那里调 `t()`。 |
| 3 | 模板自带子菜单 | 「肥鱼控制」「工具与帮助」写在模板 JSON 里、也会被复制进用户保存的编排：新增 `MENU_ACTIONS.default_label(node)`——id 是这两个、且名字仍是模板原文时按界面语言翻译；用户改过名或自建的子菜单原样。菜单与设置页的菜单编排编辑器都走它。 |
| 4 | 模板切换文字 | 「切换到新版菜单 / 切换回旧版菜单」来自模板 JSON，`add_template_switch` 按原文映射到键。 |
| 5 | 按文字找锚点 | facade 里「把新项插到『退出』前」「『隐藏肥鱼』接在『退出子肥鱼』后」是比 `action.text()`；比较的一侧钉到建菜单用的同一个键（`menu.shared.quit` / `menu.shared.close_little_fish`），不依赖两边英文碰巧相同。 |
| 6 | 别的模块的选项 | 详情卡配色名（`session_card_themes.theme_choices`）、桂冠「X（全部版本）」（`session_crown.choices`）、快捷启动里的「默认浏览器」、全角括号的「Claude Code（WSL）」→ 英文「Claude Code (WSL)」。 |
| 7 | 会话小鱼 | 菜单、详情卡按钮与提示、「工作中 · 已 3 分钟」的时长说法、「在等你批准：工具名」。 |
| 8 | 托盘 | `OverlayShell._refresh_tray_menu` 的全部条目与逐只子菜单标题（主肥鱼 / 小肥鱼 [slot-N] / 会话：标题）。 |

**红线 / 不变量**：中文界面逐字不变（菜单相关 60 个测试文件 1188 例不改一行即过）；配置里存的值不变（编排里的子菜单
名、快捷启动项名字、彩蛋标题都按原样存）；动作 id、模板 id 不变。

## 二、修改文件说明

| 文件 | 增删 | 改动 |
|---|---|---|
| `pet/context_menus/registry.py` | +43 / −17 | 11 处改写（3 条置灰原因写成键名字符串）；`label()` / `default_label()` / `icon_choice_label()` / `SUBMENU_LABEL_KEYS`；`disabled_reason()` 经 `maybe_t`；开关标签存键、建项时 `t()`；populate 的子菜单名走 `default_label`。 |
| `pet/context_menus/shared.py` | +78 / −70 | 69 处改写；`add_template_switch` 映射模板切换文字；「Claude Code（WSL）」改键。 |
| `pet/context_menus/quick_launch.py` | +12 / −3 | 3 处改写；`_display_name`（默认浏览器项按语言显示）。 |
| `pet/context_menus/legacy.py`、`fun_entry.py`、`pet/context_menu.py`、`pet/sprite_menu.py` | 各 +2～+5 | 字面量改 `t()`（彩蛋标题 / 提示的默认值不动）。 |
| `pet/sprite_menu_facade.py` | +13 / −13 | 12 处改写；两处锚点比较钉到 shared 的键。 |
| `pet/session_pet_ui.py` | +30 / −29 | 28 处改写；「在等你批准」改键、带工具名的那句改成带占位符的键。 |
| `pet/session_card_themes.py` | +4 / −1 | `theme_choices()` 显示名按 id 取键。 |
| `pet/session_crown.py` | +2 / −1 | 「X（全部版本）」改成带占位符的键。 |
| `pet/overlay_shell.py` | +15 / −14 | 托盘菜单与逐只标题改 `t()`，加 `from .i18n import t`。 |
| `pet/settings_menu_layout_editor.py` | +8 / −7 | 编辑器里的名字走 `default_label`；图标选项按值取显示名、按下标取回值（不再按中文名反查）。 |
| `pet/locale/zh.json`、`en.json` | 各 +213 / −1 | 212 个 `menu.*` 键。 |
| `scripts/capture_context_menu.py`（新） | +67 / −0 | 把新版右键菜单和「Agent 联动」子菜单按指定语言渲染成 PNG。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_menu_english.py` | +179 / −0 | 两种模板英文无中文（只剩彩蛋标题）、尾部「Fish Settings, Quit」（锚点英文下对得上）、模板子菜单名与切换文字英文；中文菜单不变；置灰提示英文；会话小鱼菜单与配色子菜单英文；托盘菜单英文与逐只标题；动作名 / 置灰原因 / 图标选项 / `default_label`（模板原文翻译、改过名的原样）跟随语言；会话时长说法英文；212 个键中英占位符一致。 |

### 未改动

- 彩蛋标题与提示（配置内容，见上）。
- 角色名、动画片段名、对话背景主题名（内容名）。
- 旧拓扑 `app.py` 的兜底托盘菜单（overlay 下不用）。
- 聊天窗、灵动岛之外的气泡里由别的模块拼的中文。

## 三、实现要点

- **复用设置页那套脚本**：AST 抽取（字节级偏移，按原始字节解码保留 CRLF）→ 人工英文 → 改写成 `t()` 并写表、校验占位符；
  这次给改写脚本加了两样：相对导入的点数按目录层级算（`pet/context_menus/` 要 `..`），以及「写成键名字符串」模式
  （给导入时实例化的 `__init__` 用）。
- **数据里的中文怎么办**：凡是会被存进配置的（编排里的子菜单名、快捷启动项名、彩蛋标题），不改数据，只在显示时判断
  「还是内置原文吗」——是就按语言显示，用户改过就原样。

## 四、性能分析

和设置页同一机制：`t()` 是一次字典查表，表在进程内只读一次。右键菜单每次弹出时建一次，新增约 60 次查表。

| 指标 | 实测 | 归属 |
|---|---|---|
| 语言表 | zh 1170 键（menu.* 212）；表读一次缓存 | 进程内 1 次 |
| 菜单建一次多出的查表 | ~60 次字典查找 | 每次右键 |
| 菜单相关测试族 | 60 个文件 1188 例 59 s（与改动前同量级） | — |

**结论**：① 稳态零开销；② 每次右键多 ~60 次字典查找，相对建 QMenu / 画图标可以忽略到测不出（没有单独计时）；
③ 无新系统调用 / 网络 / 线程；④ 内存：表里多 ~200 个短字符串。

## 五、实机运行记录

- **改动前**（HEAD 临时 worktree，英文界面，`english_menu.py` 探针）：新版模板 `72 entries with Chinese`、旧版 `64`，顶层
  `['厉害了我的鲸', '护驾', 'AI 对话', ……, '肥鱼设置', '退出']`。
- **改动后**：新版 `1`（彩蛋标题）、旧版 `0`；顶层 `['厉害了我的鲸', 'Rally', 'AI chat', 'Look at the screen', 'Play animation', …,
  'Claude Code (WSL)', 'Fish controls', 'Quick launch', 'Tools and help', 'Agent link', 'Screen awareness', 'To-do reminders',
  'Fish Settings', 'Quit']`。
- **红灯**：新测试拷进 HEAD worktree 是收集期 `ImportError`（`icon_choice_label` 还不存在）——行为层面的改动前证据看上面的探针数字。
- **截图**（`QT_QPA_PLATFORM=windows` 真实字体，`scripts/capture_context_menu.py --language en`）：
  `docs/screenshots/menu-english-2026-10-16/menu-en.png`、`menu-agent-link-en.png`，看过：图标、分组、子菜单箭头、勾选都在，
  英文没有被截断。
- 肥鱼已重启（`acquired pid=11820`，日志无 Traceback），用户的配置里界面语言是 English，右键即可看到英文菜单。
  本机没有能点真实菜单的自动化工具，以上是渲染证据。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `ruff check pet tests scripts` | All checks passed |
| 聚焦 | `pytest -q tests/test_menu_english.py` | 9 通过 |
| 菜单相关族 | 名字含 menu / tray / sprite / session_pet / context / youtube / claude_launchers / work_briefing / work_notes / slack / vscode / quick_launch / fun_entry / desktop_pet_features / i18n / settings_english / overlay_shell / rally / spawn 的 60 个文件 | 1188 通过，1 失败 = 既有基线（路径超 260） |
| 全量 | `python -m pytest -q -p no:cacheprovider`（offscreen，临时 APPDATA） | `4 failed, 5378 passed, 11 skipped in 521.82s (0:08:41)`，4 个失败全是本机既有的环境性基线（路径超 260；两个子进程输出按 cp1252 解码；多显示器负原点）。 |

## 七、已知限制与后续

- 聊天窗（AI 对话窗口）还没翻。
- 换语言后，已经弹出的菜单不会就地刷新；下次右键即是新语言（菜单每次弹出都重建）。
- 新增菜单项时文案直接写 `t("menu.…")`，动作名加进 `ACTION_LABELS` 的同时在两张表里加 `menu.action.<id>`；
  `test_menu_english` 会拦住漏网的。

## 八、风险与回滚

- 纯界面文案；`git revert` 即可，无配置迁移。
- 风险点：按菜单文字找锚点的逻辑——已把两处比较钉到与建菜单相同的键；若以后再加「按文字找某一项」，要用同一个键，
  或改用 objectName / property 做身份。
