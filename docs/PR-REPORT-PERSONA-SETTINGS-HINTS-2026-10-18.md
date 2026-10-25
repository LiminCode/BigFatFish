# PR 报告：说清肥鱼的「性格」设在哪——人设 / 关于我 单独成节，台词模板的提示改成说真话，各加一节说明

> **基线**：`238376c`（feat(personal): 个人助理）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-18
> **范围**：8 个文件（实现 3 改 + 1 新、语言表 2、测试 1 新 + 1 改、脚本 1 新）+ 本报告 + 4 张截图
> **关联**：[`PERSONA-PHRASES-PRESET-STORAGE-2026-09-08.md`](PERSONA-PHRASES-PRESET-STORAGE-2026-09-08.md)（台词预设的存储与路由）

## 一、核心特性

用户 2026-10-18：「找出所有大肥鱼性格 / 回复的设定……自动化与联动里的文案风格与模板是在哪里？需要优化这两个地方，
写明设定在哪里、怎么起作用、会影响什么功能。」

**盘点结论**：肥鱼的「性格」是两套互不相干的系统，界面上以前没有任何地方说明这一点。

| 系统 | 存在哪 | 怎么起作用 | 影响什么 | 经过模型？ |
|---|---|---|---|---|
| 对话人设（AI 与对话）| `config.json` `chat.default_system_prompt`、`chat.about_user`（全局一份，不按服务商） | `PromptBuilder.build_messages`：人设（角色包自带的会覆盖，当前角色没有）＋关于我＋知识库说明（Claude 通道、开了知识库）→ system 消息 | 对话窗、快速对话、灵动岛对话、拖文件解读；「看看屏幕」与主动识屏只带人设 | 是 |
| 气泡台词模板（自动化与联动）| `dialogue_mode`（legacy / whale_maid / custom）、`dialogue_phrases`（global + agents）；内置两套在 `pet/persona_presets/*.json` | `agent_link._dialogue` / `app._persona_text`：custom 按 专属 → 全局 → 内置兜底；内置模式按 预设 → 兜底；多条轮换、占位符自动填 | Agent 联动气泡（开始 / 思考 / 审批 / 提问 / 完成 / 出错 / 模型访问失败 / 桥接）与余额结果 | 否 |
| 其他固定文字 | `self_talk_texts`（互动 → 候选内容）、点击动画台词（角色绑定）、语音报时 / 节日台词（语音） | 各自直接读 | 自言自语、点击台词、报时与节日 | 否 |
| 不走人设的 AI 任务 | 工作简报 / Slack 关注 / 工作笔记（WSL 公司 Claude Code）、个人简报（个人 key） | 各自固定提示词 | — | 是，但与人设无关 |

**以前界面上错的 / 误导的地方**（这次改掉）：

1. 「表达风格」的提示说它「控制肥鱼自言自语、候选内容和主动气泡的说话方式」——它不管这三样（自言自语直接读
   `self_talk_texts`；主动识屏是模型写的；唯一那条桥 `window_alerts.expression_style_text` 没有调用方）。
2. 「System Prompt」夹在「模型与连接」里 API Key 和连接测试之间，看起来像某个服务商的参数，其实是全局一份、
   换服务商不变；标签还是没翻译的英文。
3. 「留空使用基础模式台词」/「留空时自动沿用默认模式文案」——实际留空回退到的是 `agent_link.py` 里的兜底文案，不是
   「默认模式」预设那句（两者措辞不同）。
4. 「一键复制当前全部弹窗内容模板」——复制出来的是字段骨架不含现有台词，覆盖范围也只是 Agent 联动与余额气泡。
5. 两套系统各不说对方：选「鲸鱼娘女仆模式」不会改对话口吻，改人设也不会改气泡，用户只能自己踩。

**改法**（只改文案与分节，不改任何行为）：

| # | 位置 | 改动 |
|---|---|---|
| 1 | AI 与对话 | 人设 + 关于我从「模型与连接」挪出来，自成一节「人设与回复」；标签改「人设（System Prompt）」；两条提示写明「全局一份、不随服务商切换」「影响：……」「不影响：……（在哪一页）」「带上它的 / 不带的」。后面跟一节默认收起的「这些设定怎么起作用」：两套系统、各自存在哪、怎么拼、影响什么、其他固定文字在哪、哪些 AI 任务不走人设。 |
| 2 | 自动化与联动 → 文案风格与模板 | 「表达风格」提示改成只管 Agent 联动气泡与余额结果、不经模型、不影响对话口吻 / 自言自语 / 主动识屏，并指路；「专属文案对象」提示写明专属层只覆盖转述事件、留空的真实回退链；模板 JSON 提示写明只是骨架、只覆盖 Agent 与余额气泡、导入会切到自定义；逐事件编辑框占位符改成「留空用内置兜底文案」。紧跟一节默认收起的「这些台词怎么起作用」：管哪些气泡 / 不管哪些、存在哪、怎么取、模板 JSON 是什么。 |
| 3 | 通用 | 新 `pet/settings_help.py`：`help_row` / `help_section`（RichText 说明行、默认收起的折叠节），工作笔记 / 个人助理那两处的写法抽成通用。 |

**不变量**：不改任何配置键、任何回退逻辑、任何提示词；中文界面其余文案不变；英文表里不含中文。

## 二、修改文件说明

| 文件 | 增删 | 改动 |
|---|---|---|
| `pet/settings_help.py`（新） | +31 | `help_row(parent, key, title, body_html)`、`help_section(...)`：说明行放在 `SettingRow` 的提示标签里（RichText、换行、可选中），objectName 保持 `settingHint` 以沿用主题色。 |
| `pet/chat/ai_settings_page.py` | +10 / −2 | 「模型与连接」只留服务商参数；新节 `settings.ai.persona_section` 装人设、关于我、说明行 `persona_help`；标签走 `t("settings.ai.persona_prompt")`。 |
| `pet/modern_settings_dialog.py` | +11 / −3 | AI 域分节：`system_prompt` / `about_user` 从「模型与连接」移到「人设与回复」，其后 `(persona_help, 折叠)`；自动化域在「文案风格与模板」之后、自定义台词折叠框之前插入 `bubble_style_help_section`。 |
| `pet/locale/zh.json`、`en.json` | 各 +17 / −9 | 改写 8 条（`settings.ai.defines_fish_identity_tone_behavior`、`tell_fish_who_you_are`、`settings.dlg.how_fish_talks_self_talk`、`who_per_event_lines_below`、`copy_template_every_current_bubble`、`leave_blank_use_base_style`、`settings.pet.leave_blank_use_base_style` ×2），新增 8 条（人设节 / 说明节的标题、引子、正文；台词说明节同）。 |
| `scripts/capture_persona_hints.py`（新） | +67 | 把两处连同展开的说明节渲染成 PNG（中 / 英）。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_settings_persona_hints.py`（新） | +125 | 人设与关于我同在一节、不与 API Key 同节、在「AI 与对话」页；标签与提示含「不随上面的服务商切换」「影响」「不影响」「文案风格与模板」「候选内容」「带上它的 / 不带的」；说明节默认收起、正文含两套系统 / `chat.default_system_prompt` / 不经过模型。「表达风格」提示含「Agent 联动气泡」「不经过模型」「自言自语」「人设」「persona_presets」；专属文案提示含「内置兜底文案」「不是「默认模式」」；说明节位置在「文案风格与模板」之后、自定义台词折叠框之前，正文含 `dialogue_mode` / `dialogue_phrases` / 回退链；逐事件占位符不再说「基础模式」。英文版三处。 |
| `tests/test_desktop_pet_features.py` | +4 / −4 | 原断言「表达风格」提示含「自言自语 … Agent 状态」（旧措辞）→ 改成新措辞的断言。 |

## 三、实现要点

- 行 id 不变（`system_prompt` / `about_user` / `dialogue_*`）：保存、搜索、深链接都照旧；只是设置窗口按 id 重新分节。
- 说明正文里写配置键和文件名是有意的：用户问的就是「设在哪里」。
- 盘点时发现但**没动**的两处行为与文案不符：留空自定义事件回退到代码兜底而不是「默认模式」预设（2026-09-08 定的路由，
  这次只把文案改成真话）；`settings.dlg.who_per_event_lines_below` 的「仅在自定义模式生效」保留。

## 四、性能分析

| 指标 | 实测 / 说明 |
|---|---|
| 设置窗口 | 多两个 `SettingsSection`（各一行 RichText 标签）；建窗口时一次性构造，`tests/test_settings_persona_hints.py` 三例含建两次窗口共 ~3 s（offscreen），与改前同量级 |
| 运行时 | 零：没有任何逻辑改动，桌宠主进程不加载设置页 |
| 语言表 | zh +8 键 / en +8 键（说明正文各约 600 字） |

**结论**：① 稳态零开销；② 只在打开设置窗口时多建两节；③ 无新系统调用 / 网络 / 线程；④ 内存：两段说明文字。

## 五、实机运行记录

- **截图**（`QT_QPA_PLATFORM=windows` 真实字体，`scripts/capture_persona_hints.py`）：
  `docs/screenshots/persona-hints-2026-10-18/settings-persona-{zh,en}.png`（「人设与回复」一节 + 展开的说明）、
  `settings-bubble-style-{zh,en}.png`（「文案风格与模板」+ 展开的「这些台词怎么起作用」）。看过：人设已不在「模型与连接」里，
  标签「人设（System Prompt）」，提示两行写明影响 / 不影响；说明节正文分段加粗；表达风格的新提示完整显示。
- **红灯**：`tests/test_settings_persona_hints.py` 在改动前运行——人设与 API Key 同节、提示里没有「不随上面的服务商切换」、
  没有 `persona_help` 行——三例全失败；`test_desktop_pet_features` 里旧措辞的断言在改动后红、更新后绿。
- 设置窗口是桌宠拉起的独立进程，下次打开即是新代码，不需要重启桌宠。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `ruff check pet tests scripts` | All checks passed |
| 聚焦 + 相关 | `pytest -q tests/test_settings_persona_hints.py tests/test_desktop_pet_features.py tests/test_settings_english.py tests/test_i18n.py tests/test_about_user_prompt.py tests/test_architecture.py tests/test_menu_layout.py tests/test_settings_personal.py tests/test_settings_work_notes.py` | 214 通过，1 失败 = 既有基线（图片目录选择器路径超 260） |
| 全量 | 未跑 | 纯文案与分节，不改任何行为、配置键、提示词；按 AGENTS.md 的「局部展示 token」豁免。 |

## 七、已知限制与后续

- 两处行为与文案的差异只改了文案：留空自定义事件回退到代码兜底，而不是「默认模式」那句；要改成按预设回退是另一个决定。
- 聊天窗内的旧版设置对话框（`pet/chat/settings_dialog.py`）仍只编辑 System Prompt、没有「关于我」，这次没动。
- `bridge.unknown` 事件在预设里有、在 `DIALOGUE_LABELS` 里没有（设置页显示原始键）；`balance.loading` 可编辑但没有运行时调用方。

## 八、风险与回滚

- `git revert` 即可；无配置迁移。
- 风险点：行 id 若被别处按节名查找——仓库里查过，设置搜索与深链接都按行 id，不按节。
