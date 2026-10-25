# PR 报告：内置表达风格不再是黑箱——选中就能看到整套台词，「改成我的台词」一键复制成可编辑的自定义台词

> **基线**：`03126e1`（feat(settings): 说清肥鱼的「性格」设在哪）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-18
> **范围**：6 个文件（实现 2 改、语言表 2、测试 1 新 + 1 改、脚本 1 新）+ 本报告 + 4 张截图
> **关联**：[`PR-REPORT-PERSONA-SETTINGS-HINTS-2026-10-18.md`](PR-REPORT-PERSONA-SETTINGS-HINTS-2026-10-18.md)（同一天的上一步：说明文字）、
> [`PERSONA-PHRASES-PRESET-STORAGE-2026-09-08.md`](PERSONA-PHRASES-PRESET-STORAGE-2026-09-08.md)（预设的存储与路由，本次加了 §9）

## 一、核心特性

用户 2026-10-18：「气泡台词模板 / 表达风格这些需要设置成可以 edit，我不知道鲸鱼娘女仆或者其他都是怎么设置的，
对我来说是黑箱，需要直观显示出来。」

以前：选「默认模式 / 鲸鱼娘女仆模式」时，下方「自定义台词」折叠框里 30 个事件的编辑框全是空的（只有占位符），
那两套台词只存在于仓库的 JSON 里；「一键复制模板」复制出来的也是空骨架。要改口吻只能从零手写。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 内置模式只读预览 | 「表达风格」选「默认模式」或「鲸鱼娘女仆模式」时，折叠框改名「『鲸鱼娘女仆模式』的台词（只读；要改先点「改成我的台词」）」，30 个事件的编辑框只读地显示那套台词（一行一条，和 `pet/persona_presets/*.json` 一致）；换模式即刷新。预览期间「专属文案对象」下拉置灰（内置只有一层）。 |
| 2 | 改成我的台词 | 「表达风格」右边多一个按钮「以『X』为底改成我的台词」：把当前内置模式的整套台词复制进自定义台词（global 层）、把表达风格切到「自定义台词」、展开折叠框、编辑框解锁。自定义台词里已有内容时先问一次（Agent 专属层不动）。 |
| 3 | 预览不污染自定义 | 预览期间编辑框里是内置台词，保存 / 切层 / 导出都不会把它写回 `dialogue_phrases`：用户在自定义模式下打过的字原样保留，切回自定义时恢复。 |
| 4 | 导出带台词 | 「一键复制模板」现在带当前显示的那套台词（内置模式就是内置的，自定义就是你的）：既是备份，也能直接发给 AI 依角色卡改写再导入。导入前先切到自定义模式，免得写进预览被覆盖。 |
| 5 | 提示更新 | 「表达风格」与模板 JSON 两条提示写明这套流程；中英文。 |

**不变量**：运行时的台词路由（`agent_link._dialogue`、`PhrasePicker`）一行没动；内置 JSON 仍只读、随程序分发；
配置键不变（`dialogue_mode` / `dialogue_phrases` / `dialogue_last_scope`）；Agent 专属层的编辑与保存照旧。

## 二、修改文件说明

| 文件 | 增删 | 改动 |
|---|---|---|
| `pet/settings_pet_controls.py` | +88 / −10 | `_builtin_lines_text(mode)`；`_apply_dialogue_mode_view(host)`（内置 → 只读显示那套、置灰专属层下拉、显示并改名「改成我的」按钮、折叠框改名；自定义 → 恢复缓冲、解锁）；`_adopt_builtin_phrases(host, confirm=None)`（确认可注入）；`_dialogue_flush_scope` 在预览期间不写缓冲；`_current_dialogue_template` 带当前显示的台词；导入先切到自定义；建控件处挂 `dialogue_adopt_btn`、`_dialogue_preview` 标志、`dialogue_mode_select.currentIndexChanged` → 刷新视图。 |
| `pet/modern_settings_dialog.py` | +5 / −1 | 「表达风格」行的控件改成 `ResponsiveActionRow(下拉, [改成我的])`；折叠框建好后调一次 `_apply_dialogue_mode_view`；包一层 `_adopt_builtin_phrases` 方法。 |
| `pet/locale/zh.json`、`en.json` | 各 +6 / −2 | 新键 `settings.pet.adopt_builtin*`（按钮、带模式名的按钮、提示、确认标题与正文）、`settings.dlg.builtin_lines_readonly`；改写「表达风格」与模板 JSON 两条提示。 |
| `scripts/capture_dialogue_preview.py`（新） | +67 | 预览（鲸鱼娘）与「改成我的」之后各一张（中 / 英）。 |
| `docs/PERSONA-PHRASES-PRESET-STORAGE-2026-09-08.md` | +10 | §9：设置页的预览 / 复制流程与「预览不写缓冲」的约束。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_dialogue_preview.py`（新） | +118 | 选鲸鱼娘 → 编辑框只读、内容 = 预设、专属层下拉置灰、折叠框标题、按钮文案；换成默认模式即刷新。自定义模式下改过字再切去预览，保存：存的是用户的台词、模式是预览的模式；切回自定义恢复。「改成我的」：空自定义不问、整套复制、切自定义、展开、可编辑、保存落盘；已有自定义内容时先问，拒绝则不动，同意则覆盖。英文。 |
| `tests/test_settings_and_resources.py` | +10 / −6 | 原「导出 phrases 一律留空」两处断言改成「导出带当前显示的台词」（内置模式 = 内置台词；自定义 = 用户的）。 |

## 三、实现要点

- 不碰运行时：预览只是把 `builtin_phrases(mode)` 摆进编辑框；真正的「可编辑」靠复制成自定义台词，内置 JSON 继续只读。
  这样不需要新的存储，也不会出现「改了内置模式但不知道存在哪」的第二个黑箱。
- `_dialogue_preview` 标志是关键约束：所有会把编辑框写回缓冲的路径（切层、保存、导出）都先看它；导入模板因此要先切到自定义。

## 四、性能分析

| 指标 | 实测 / 说明 |
|---|---|
| 换一次表达风格 | 30 个 `QPlainTextEdit.setPlainText` + 只读切换，offscreen 实测 < 20 ms（`test_dialogue_preview` 5 例含 5 次建窗共 ~4 s，与同类设置测试同量级） |
| 运行时 | 零：桌宠主进程不加载设置页，台词路由没动 |
| 语言表 | zh / en 各 +6 键 |

**结论**：① 稳态零开销；② 只在设置窗口里换模式时多一次 30 框刷新；③ 无新系统调用 / 网络 / 线程；④ 内存：预览文本与缓冲各一份（几 KB）。

## 五、实机运行记录

- **截图**（`QT_QPA_PLATFORM=windows` 真实字体，`scripts/capture_dialogue_preview.py`）：
  `docs/screenshots/dialogue-preview-2026-10-18/preview-whale-maid-{zh,en}.png`（选鲸鱼娘：折叠框改名、按钮「以『鲸鱼娘女仆模式』为底改成我的台词」、
  编辑框只读列出台词）、`adopted-custom-{zh,en}.png`（点过之后：表达风格 = 自定义台词、按钮隐藏、折叠框恢复原名、编辑框可编辑且内容是刚复制的那套）。
- **红灯**：`tests/test_dialogue_preview.py` 在改动前运行——没有 `dialogue_adopt_btn`、编辑框不只读、折叠框标题不变——5 例全失败；改后绿。
- 设置窗口是独立进程，下次打开即是新代码，不需要重启桌宠。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `ruff check pet tests scripts` | All checks passed |
| 聚焦 + 相关 | `pytest -q tests/test_dialogue_preview.py tests/test_settings_and_resources.py tests/test_settings_persona_hints.py tests/test_settings_english.py tests/test_i18n.py tests/test_desktop_pet_features.py tests/test_menu_layout.py tests/test_persona_*.py tests/test_personal_*.py` | 280 通过，1 失败 = 既有基线（图片目录选择器路径超 260） |
| 全量 | 未跑 | 只改设置页的台词编辑区与导出；运行时路由、配置键、生命周期都没动；按 AGENTS.md 的「局部展示 token」豁免。 |

## 七、已知限制与后续

- 预览只有 global 一层（内置模式本来就没有 Agent 专属层）。
- 留空的自定义事件仍回退到代码兜底文案（不是「默认模式」那句）——用「改成我的台词」起步的话所有事件都有内容，基本碰不到。
- 「恢复成内置」= 把表达风格切回默认 / 鲸鱼娘；自定义台词不会被清掉。

## 八、风险与回滚

- `git revert` 即可；无配置迁移。
- 风险点：预览标志漏判导致内置台词写进自定义——`test_previewing_never_overwrites_the_custom_lines_even_on_save` 锁住。
