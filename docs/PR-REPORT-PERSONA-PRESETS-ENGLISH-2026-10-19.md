# PR 报告：内置表达风格的英文版——两套预设各加一份英文 JSON，按界面语言切换

> **基线**：`3cc5e27`（feat(i18n): 其余界面英文化）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-19
> **范围**：6 个文件（数据 2 新、实现 1、测试 1 新、文档 1、本报告）+ 2 张截图
> **关联**：[`PERSONA-PHRASES-PRESET-STORAGE-2026-09-08.md`](PERSONA-PHRASES-PRESET-STORAGE-2026-09-08.md) §9、
> [`PR-REPORT-REST-ENGLISH-2026-10-19.md`](PR-REPORT-REST-ENGLISH-2026-10-19.md)「后续」第一条、
> [`PR-REPORT-DIALOGUE-PREVIEW-2026-10-18.md`](PR-REPORT-DIALOGUE-PREVIEW-2026-10-18.md)（设置页的预览与「改成我的台词」）

## 一、核心特性

用户 2026-10-19：「给两套预设各加一份英文 JSON 按界面语言切换」。此前英文界面下 Agent 联动的气泡（开始 / 思考 / 审批 /
提问 / 完成 / 出错…）仍说中文，因为两套内置台词是中文数据文件。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 英文数据文件 | `pet/persona_presets/legacy.en.json`、`whale_maid.en.json`：与中文版同样的 30 个事件、每事件 3 条，占位符逐条对齐（`{name}` / `{sessionName}` / `{tool}` / `{step}` …）。默认模式是中性口吻；鲸鱼娘版保留「Master~」「Hmph」「Uu~」「you may call me clever, but never fat」这些性格记号。 |
| 2 | 按界面语言切换 | `builtin_phrases(mode, language=None)` 缺省取 `i18n.current_language()`：有该语言的文件就按键覆盖中文，缺的键回退中文那条；整个文件不存在就整套中文。再加语言只要放 `<mode>.<lang>.json` 并登记到 `_PRESET_LANGUAGES`。 |
| 3 | 影响面 | 运行时渲染（`PhrasePicker.get` → `agent_link._dialogue` 的全部 Agent 气泡与余额结果）、设置页「文案风格与模板」的只读预览、「改成我的台词」复制的那套——三处都跟界面语言。用户自己的「自定义台词」不受语言影响（那是用户数据）。 |

**不变量**：中文界面逐字不变（`load_builtin_presets()` 的返回值、`phrase_keys()`、`default_phrases()` 仍只看中文文件，
既有 239 例不改一行即过）；事件词表仍由中文文件定义；配置键不变。

## 二、修改文件说明

| 文件 | 增删 | 改动 |
|---|---|---|
| `pet/persona_presets/legacy.en.json`（新） | +152 | 默认模式英文版，30 事件 × 3 条。 |
| `pet/persona_presets/whale_maid.en.json`（新） | +152 | 鲸鱼娘女仆模式英文版，30 事件 × 3 条。 |
| `pet/persona_phrases.py` | +28 / −9 | `_PRESET_LANGUAGES = ("en",)`、`_presets_by_lang` 注册表；`_read_preset_file(mode, language="")`（语言版缺失只记 debug，不告警）；`load_builtin_presets` 同时读语言版；`builtin_phrases(mode, language=None)` 按界面语言合并；模块说明更新。 |
| `docs/PERSONA-PHRASES-PRESET-STORAGE-2026-09-08.md` | +11 | §9：英文版的数据、加载、影响面、怎么再加语言。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_persona_presets_english.py`（新） | +92 | 两份英文文件键集合 = 中文版、每条 ≤240 字 / 每键 ≤8 条、英文里无中文、占位符不超出中文版；`builtin_phrases` 跟界面语言、指定语言、未知语言整套中文、缺键按键回退；`PhrasePicker.get` 英文渲染且回退文案照旧、切回中文不变；设置页只读预览与「改成我的台词」用英文那套。 |

## 三、实现要点

- 不改事件词表的来源：英文文件只能「覆盖」中文已有的键，多出来的键不会凭空成为新事件（`phrase_keys()` 只看中文）。
- 语言在**渲染时**取，不在加载时取：用户在设置里切换语言后，下一条气泡就是新语言，不用重启；设置页的预览同理。
- `builtin_phrases` 内部惰性导入 `i18n`，避免 `persona_phrases` ↔ `i18n` 在导入期互相依赖。

## 四、性能分析

| 指标 | 实测 / 说明 |
|---|---|
| 启动 | 多读 2 个 JSON（各 ~8 KB），一次性 |
| 每条气泡 | `builtin_phrases` 多一次 `current_language()` + 一次字典合并（30 键）；`test_persona_presets_english` 4 例含一次建设置窗共 ~1 s（offscreen） |
| 内存 | 多两套 90 条短字符串 |

**结论**：① 稳态零开销；② 每条 Agent 气泡多一次 30 键的字典合并，微秒级；③ 无新 I/O / 线程；④ 内存可忽略。

## 五、实机运行记录

- **截图**（`QT_QPA_PLATFORM=windows` 真实字体，`scripts/capture_dialogue_preview.py --language en`）：
  `docs/screenshots/persona-presets-english-2026-10-19/preview-whale-maid-en.png`（英文界面选 Whale-maid：折叠框里列出的是英文台词，
  如「Master~ {name} finished this round; go see what it made.」）、`adopted-custom-en.png`（点「Start my lines from “Whale-maid”」后：
  自定义台词里是英文那套、可编辑）。
- **红灯**：`tests/test_persona_presets_english.py` 在改动前——没有英文文件、`builtin_phrases` 不认 `language`——4 例全失败；改后绿。
- 肥鱼已重启（结束不含 `--settings` 的主进程，`run.bat` 拉起，日志无 Traceback）；用户配置里界面语言是 English、表达风格是
  默认模式，下一次 Agent 联动气泡即为英文。本机没有能触发真实 Agent 事件的自动化手段，气泡渲染由 `PhrasePicker` 的单元层覆盖。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `ruff check pet tests` | All checks passed |
| 聚焦 + 相关 | `pytest -q tests/test_persona_presets_english.py tests/test_persona_presets.py tests/test_persona_settings.py tests/test_persona_template.py tests/test_persona_template_rendering.py tests/test_dialogue_preview.py tests/test_agent_link.py tests/test_i18n.py tests/test_settings_persona_hints.py tests/test_architecture.py` | 239 通过 1 跳过 |
| 全量 | 未跑 | 只加数据文件与一个按语言合并的读取函数；运行时路由、配置键、生命周期不变；按 AGENTS.md 的「局部展示 token」豁免。 |

## 七、已知限制与后续

- 英文台词是一次性译文，口吻可按喜好再改：选内置模式看预览，「改成我的台词」后逐条编辑。
- `agent_link.py` 里的代码兜底文案仍是中文（只在预设缺键时才会出现；两套英文文件键齐全，英文界面下碰不到）。
- 听歌时的八句、节日 / 报时语录仍是中文内容，不在本次范围。

## 八、风险与回滚

- `git revert` 即可；删掉两个 `.en.json` 也能退回整套中文（缺文件只记 debug）。
- 风险点：英文文件里用了中文版没有的占位符会原样露出 `{xxx}`——契约测试逐条拦住。
