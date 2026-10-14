# PR 报告：界面语言（中文 / English）第一片——灵动岛胶囊与展开卡片

> **基线**：`0e9ab97`（feat(island): 「最近的对话」的来源图标用本机程序自己的图标）
> **分支**：`feature/claude-session-fish`　**日期**：`2026-10-14`
> **范围**：21 个文件（实现 16、测试 5；含本报告与索引）

## 一、核心特性

用户要加英文支持，不急着一次做完：先做灵动岛胶囊和展开卡片，之后逐片推进。方案与
措辞是先评估、后由用户拍板的（2026-10-14）：

- **键用英文标识符**（方案 B：`island.card.chat`），中英各一张表，而不是用中文原文做键。
  理由是工程上清晰：改中文措辞不会悄悄弄丢英文，同词异译天然分开。代价是全部文字要
  进表、一片要一次做完——所以按片推进。
- 语言只给「中文 / English」两项，入口放设置页「常规」。
- 英文要拟人一点：休息中 → **Napping**，工作简报 → **Daily Briefing**，其余按草案。
- 文档不翻，记为待办。

| # | 能力 | 说明 |
|---|---|---|
| 1 | `pet/i18n.py` | `t(key, **values)`：当前语言查表 → 缺则退回中文 → 再缺退回键名；`{n}` 占位；英文单复数用 `<键>.one` / `<键>.other` |
| 2 | `pet/locale/zh.json` / `en.json` | 64 个键；中文表就是原来代码里的字 |
| 3 | 配置项 `ui_language` | 默认 `zh`；`Config` 加载、重载、`set`、保存时都把它同步给 `i18n`（设置窗口是另一个进程，靠重载那一步生效） |
| 4 | 设置页「常规」第一节「语言 / Language」 | 下拉「中文 / English」；保存后桌宠的配置监视器重载 → 岛重画 → app 把算好的文字重推一遍，不用重启 |
| 5 | 覆盖面 | 胶囊（会话计数、今日用量占位）、卡片（标题行、三个按钮、余额与用量占位、简报按钮提示）、最近的对话（表头、进行中、右键菜单、时间、来源、动作结果提示）、连接图标的悬停说明、余额说明、岛对话气泡的标题与按钮 |

**红线 / 不变量**

- 中文模式下每一处文字与改动前**逐字相同**（`test_the_same_functions_still_say_exactly_what_they_used_to_in_chinese`、
  `test_time_and_origin_in_chinese_are_unchanged`，以及既有按中文断言的岛 / 会话测试全部通过）。
- 两张表键集合一致（英文允许 `.one`/`.other` 对代替一个键）；代码里 `t("…")` 用到的键都在
  中文表里；键名合规（`test_the_two_tables_cover_the_same_keys`、`test_every_key_used_in_code_exists_in_the_chinese_table`）。
- 缺翻译时用户看到的是中文，不是键名。
- `claude_hooks.PHASE_TEXT` 仍可当字典用（`in` / `[]` / `.get` / `dict()`），只是取值按当前语言
  ——会话小鱼头顶的状态词因此也跟着换了（它在岛之外，算顺带）。
- 桌宠右键菜单、设置页其余部分、气泡台词、角色台词包：不在这一片，仍是中文。

## 二、修改文件说明

增删取自 `git diff 0e9ab97 --numstat`；新增文件给的是总行数。

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/i18n.py`（新增） | +89 / −0 | 查表层：语言规整、表的读取与缓存、`t()`、键名校验 |
| `pet/locale/zh.json`（新增） | +71 / −0 | 中文表（64 键） |
| `pet/locale/en.json`（新增） | +78 / −0 | 英文表（64 键，7 个带单复数） |
| `pet/settings_language.py`（新增） | +29 / −0 | 「界面语言 (Language)」一行：下拉与保存 |
| `pet/config.py` | +7 / −0 | 默认值、`reload()` 白名单、`_normalize_pet_settings` 规整并同步给 `i18n`、`set()` 触发规整的键集合加 `ui_language`、`reload()` 里同步一次（外部改的语言在重载这一步就生效） |
| `pet/modern_settings_dialog.py` | +4 / −0 | import 1 行、建行 1 行、「常规」域认领 1 行（没认领的行会掉进「自动化与联动 → 待分类」，第一次渲染就是这么发现的）、保存 1 行 |
| `pet/dynamic_island.py` | +36 / −12 | 占位文案、三个按钮、简报按钮提示改查表；`_sync_card_labels` 每次重写按钮文字并让面板 `retranslate()`；`refresh_from_config` 时把还是占位值的几处按新语言重写（`_relabel_placeholders`，有真实数据的不动） |
| `pet/island_history_panel.py` | +16 / −8 | 表头、「进行中」、右键菜单改查表；记住未省略的表头全文 `header_text`（省略只为显示）；`retranslate()` |
| `pet/claude_hooks.py` | +28 / −11 | `PHASE_TEXT` 变成按当前语言取值的 `Mapping`；胶囊短标签、卡片计数、「没有在用的会话」、「等 N 个」改查表 |
| `pet/claude_session_history.py` | +10 / −8 | `ago_text`、`where` 改查表 |
| `pet/session_history_service.py` | +9 / −8 | 8 条动作结果改查表 |
| `pet/api_key_monitor.py` | +8 / −7 | 5 条体检说明改查表 |
| `pet/claude_usage.py` | +6 / −4 | 今日用量的一行与明细改查表 |
| `pet/app.py` | +22 / −10 | 余额说明 6 条、最近对话的状态行 2 条改查表；新增 `_repush_island_texts`：配置重载后把会话计数、最近对话、卡片标题重推一遍（语言换了，岛自己重画不够） |
| `pet/island_chat.py` | +3 / −2 | 岛对话气泡的标题与「显示桌宠」按钮 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_i18n.py`（新增） | +103 / −0 | 7 条：语言规整；占位与单复数；缺英文退中文、缺键退键名、多余占位值不碍事；两表键一致 + 键名合规 + 无空文案；代码里的键都在表里；四个阶段的动态键都在；`Config` 加载 / `set` / 重载 / 坏值都同步语言 |
| `tests/test_island_english.py`（新增） | +160 / −0 | 8 条：英文下的计数与标题、时间与来源；中文下逐字不变（两条）；卡片按钮与占位、简报提示；最近的对话面板（表头、进行中、右键菜单）；运行中换语言后已展开的岛跟着换；设置行在「常规」第一节且持久化 |
| `tests/test_config_schema.py` | +1 / −0 | 白名单快照登记 `ui_language` |
| `tests/test_architecture.py` | +3 / −1 | `modern_settings_dialog.py` 行数预算 2395 → 2399（带日期说明） |

### 未改动

- `pet/balance.py` 的峰谷文案（DeepSeek 专用、用户不用）、`claude_usage_monitor.py`（只转发）。
- 会话小鱼详情卡、桌宠右键菜单、气泡：下一片。

## 三、实现要点

**语言状态放哪。** `i18n` 里一个模块级变量；`Config` 是唯一的写入者（加载 / 重载 / `set` /
保存都会同步）。这样所有 `t()` 调用不用拿到 `Config`，纯函数（`ago_text`、`summarize_sessions`）
也能用。代价是测试里每新建一个 `Config` 都会把语言设回它的配置值——英文测试建岛时要先把
`ui_language` 写进那份配置。

**为什么 `PHASE_TEXT` 做成 `Mapping` 而不是函数。** 它被三处当字典用（`in`、`[]`、`.get`），
还有测试直接 `ch.PHASE_TEXT["resting"]`。一个按当前语言取值的 `Mapping` 让这些调用方一个
都不用改，也顺带让小鱼头顶的状态词跟着语言走。

**运行中换语言的两条链。** 岛自己写的字（按钮、占位、表头、进行中、菜单）在
`refresh_from_config` → `_sync_card_labels` / `retranslate()` 里重写；app 算好塞给岛的字
（会话计数、卡片标题行、最近对话的每一行）由 `_repush_island_texts` 在配置重载后重推。
两条都挂在既有的配置重载路径上，没有新信号。

**占位值怎么跟语言。** 「余额 --」「今日 --」在真实数据来之前就显示着；换语言时只有
还是占位值的才重写（判断「现在显示的是不是任一语言下的占位文案」），有真实数据的不动。

**英文措辞里的几处取舍。** 「等你批准 / 等你回复」用 *Needs your OK* / *Waiting on you*，
比 *Awaiting approval* 更像一条鱼在说话；`ago` 用 *11 min ago* / *3 h ago*，胶囊和列表
右栏放不下 *minutes*。表头在测试环境的回退字体下会省略最后一个字母（297 px > 288 px），
真实字体（Segoe UI）下放得下——所以测试断言未省略的全文 `header_text`，渲染图里核对
显示。

**没有采用的做法**

- 中文原文做键（方案 A）：用户选了 B，理由见 §一。
- Qt 自带的 `tr()` / `.ts` 文件：要上 `lupdate` / `lrelease` 工具链，表格也不是人可直接改的 JSON。
- 把语言切换做成需要重启：现有的配置重载链路够用。

## 四、性能分析

**方法**：一次性脚本，`QT_QPA_PLATFORM=offscreen`，n=20000 / 5000。

| 指标 | 实测 | 归属 |
|---|---|---|
| `t()` 中文、无占位 | 中位 0.30 µs | 每处文字 1 次，在原本就要建控件 / 拼字符串的地方 |
| `t()` 英文、带单复数 | 中位 0.60 µs | 同上 |
| `summarize_sessions`（3 个会话） | 中位 5.9 µs，p95 7.7 µs | 卡片刷新时 1 次 |
| `session_counts` | 中位 1.7 µs | 会话状态变化时 1 次 |
| 两张表读入 | 0.36 ms | 进程启动后第一次 `t()` |
| 换语言后的重推 | 等于一次正常的岛刷新（会话计数 + 最近对话 + 卡片），没有单独量 | 换语言时 1 次 |
| 新测试 | 15 条约 1.6 s | — |

**结论**：没有稳态开销；每处文字多一次字典查找（亚微秒）；没有新的系统调用、线程、
磁盘（两个 JSON 启动后各读一次）、网络；内存多两张 64 键的表。

## 五、实机运行记录

```text
真实字体渲染（不上屏），编造的会话与行：
英文岛：胶囊「Today 2.68M · 1 working · 2 napping」；卡片「Claude Code · 1 working · 2 napping」
        「web · Working ｜ api (WSL) · Napping and 3 in all」；列表表头「Recent chats (3) · Collapse」、
        右栏「Live / 9 h ago / yesterday」、来源「Terminal · WSL」；按钮「Hide the fish / Chat / Settings」
中文岛：同一布局，文字与改动前相同
设置页「常规」：第一节「语言 / Language」，下拉「中文 / English」
        （第一次渲染时这一行不在「常规」而在「自动化与联动 → 待分类」：设置页按领域重排所有行、
        没认领的会被归到待分类；补了认领之后在「常规」第一节）
```

真实桌宠在提交后重启。

**没有验证的部分**

- **没有在真实桌面上切到英文看过。** 切换链路（设置窗口保存 → 配置重载 → 岛重画 + app 重推）
  有用例覆盖到「岛对象上的文字换了」，真实进程间的那一下没有人去点。
- 玻璃 / 浅色配色下的英文没有渲染；英文比中文长，胶囊宽度按字体度量实时算（渲染图里
  352 px 对 340 px），卡片里固定列宽的「进行中 / Live」一栏按文字量宽。
- 「余额峰谷」那一类 DeepSeek 文案没有翻（用户不用）。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests`、`git diff --check` | 通过 |
| 红 → 绿 | `pytest -q tests/test_i18n.py tests/test_island_english.py` | 实现前 `6 failed, 8 passed`（模块已有、调用点未接）；接线后剩 3 条红——建岛的测试没把语言写进配置、面板不重写文字、表头在回退字体下被省略——分别改测试夹具、加 `retranslate()`、断言全文后全绿；设置行那 1 条是后补的（先发现行掉进「待分类」，补认领后写的） |
| 聚焦 + 相关 | 两个新文件 + 岛的全部家族 + 会话 / 历史 / hook / 小鱼标题 + `test_config_schema` `test_config_instance` `test_architecture` `test_settings_and_resources` `test_menu_layout` | 332 passed（认领修正前）；修正后 `test_architecture` `test_settings_and_resources` `test_menu_layout` 与两个新文件重跑 121 passed |
| 受影响时序族满载 3 遍 | — | 不适用：没有新增线程或等待 |
| 全量 | `python -m pytest -q -p no:cacheprovider`（隔离 worktree，`0e9ab97` 加本改动） | 最终代码：`5 failed, 5185 passed, 11 skipped in 432.41s`，5 个就是这台机器固定的环境性失败。补认领之前的那一版也跑过一次全量：`8 failed, 5181 passed`，多出的 3 个（设置页领域归属的三条）正是语言行掉进「待分类」造成的，补认领后单独重跑通过，再由这次全量确认。这次运行之后只改了本报告与索引登记 |

## 七、已知限制与后续

- 只覆盖灵动岛；其余界面仍是中文。下一片建议：会话小鱼的详情卡与气泡提示，再是桌宠
  右键菜单，最后是设置页。
- 「跟随系统」没有做；要加是 `normalize_language` 里多一个值。
- 英文表里几处拟人措辞是我起的草案（`Needs your OK`、`Waiting on you`、`nobody's on duty`），
  用户要换直接改 `en.json`，不用动代码。
- 文档不翻译（待办）。

## 八、风险与回滚

- **影响面**：中文模式下文字逐字不变；新增配置项 `ui_language`。
- **配置 / 落盘**：旧版本读到 `ui_language` 会忽略。
- **回滚**：`git revert` 后重启桌宠。
