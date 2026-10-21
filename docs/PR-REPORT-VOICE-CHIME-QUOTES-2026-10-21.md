# PR 报告：语音报时的内置台词库在设置页里看得见、改得了（中 / 英各一份）；自定义台词改成追加而不是替换

> **基线**：`e238e268`（feat(slack-watch): Slack 关注存档 + 「Slack 关注」页）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-21
> **范围**：5 个实现文件（含 2 张语言表）+ 1 个新测试文件 + 3 个旧测试文件 + 截图脚本 + 2 张截图 + 本报告
> **关联**：语音报时原始实现见 `pet/voice_chime.py` 模块说明；节日提醒的追加语义 `festival.quote_pool` 是先例

## 一、核心特性

用户 2026-10-21：报时后面那句话来自代码里的内置台词库（`voice_chime_quotes.py`，中文 120 条、英文 96 条），
对用户是黑箱；要求「make it shows in config and editable, for english and chinese」，并且自定义台词
「will be not replace, but append」。

| # | 改动 | 说明 |
|---|---|---|
| 1 | 内置库可见可改 | 设置页「语音 → 语音报时 → 台词 / 歌词」一节新增「内置台词 / 歌词（中文）」「内置台词 / 歌词（英文）」两个多行编辑框，预填代码里的整份内置库（一行一条），可以删、改、加；每框下面一个「恢复内置」按钮（没改过时置灰）。 |
| 2 | 存法 | 新配置键 `voice_chime_builtin_quotes_zh / _en`：保存时编辑框内容和代码里的内置库一字不差 → 存空串（= 原样，以后版本往代码里加新句子还能跟上）；改过 → 整份存进去，之后以它为准。 |
| 3 | 自定义 = 追加 | `quote_pool(cfg)` = 内置（或改过的内置）+ 自定义追加（和内置重复的不重复加），整体走原来的「每天洗牌 + 日内顺序」轮换。以前自定义非空就整体替换内置库。想去掉内置里的某句，直接在内置库编辑框里删。 |
| 4 | 文案 | 自定义两行的提示改成「追加在上面内置库的后面一起轮换」；中英文齐。 |

不变：报时文本本身、每天洗牌 / 日内顺序的轮换规则、语音合成与缓存（缓存键按文本哈希，库变了只是新句子第一次合成）。

## 二、修改文件说明

| 文件 | 增删 | 改动 |
|---|---|---|
| `pet/voice_chime.py` | +27 / −7 | `default_chime_config` 加两键；`builtin_quotes_text(language)`；`normalize_chime_config` 多 `builtin_quotes_zh / en`；新 `quote_pool(cfg)`（内置或改过的内置 + 自定义追加、去重保序）；`pick_quote` 改用它。 |
| `pet/voice_chime_settings.py` | +65 / −7 | `_builtin_editor(language)`：预填的编辑框 + 「恢复内置」（`textChanged` 时按是否等于内置原文置灰）；`_builtin_value`（等于原文存空串）；台词 / 歌词一节四行：内置中、自定义中、内置英、自定义英；`apply_to_config` 写 13 键；模块说明改写。 |
| `pet/config.py` | +4 / −0 | 默认值与键列表各加 `voice_chime_builtin_quotes_zh / _en`。 |
| `pet/locale/zh.json`、`en.json` | 各 +9 / −3 | 新键 `settings.voice.builtin_lines_lyrics_chinese / _english / builtin_lines_hint_zh / _en / restore_builtin / restore_builtin_hint`；改写 `one_per_line_if_filled`、`one_per_line_same_rules`（追加语义）。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_voice_chime_builtin_quotes.py`（新） | +121 | 默认值 / normalize 带新键、`builtin_quotes_text`；库 = 内置 + 自定义追加（顺序、去重、语言分开）；改过的内置库取代代码列表、空 = 代码列表、照样轮换；设置页：编辑框预填内置全文、「恢复内置」没改时置灰、没改保存为空串、改了存整份、恢复后再保存回空串；配置里有改过的就显示改过的；自定义提示含「追加」不含「替换」；英文文案与键对齐。 |
| `tests/test_voice_chime.py` | +14 / −12 | 平铺键集合加两键；「库短时回环」改用改过的内置库；「自定义替换内置」改成「自定义追加」；「自定义贯通到报时语句」改成内置一句 + 自定义一句两小时都出现。 |
| `tests/test_config_schema.py` | +4 / −0 | 快照两处各加两键。 |
| `tests/test_menu_layout.py` | +1 / −1 | 「语音」域的报时行数 12 → 14。 |

### 其他

| 文件 | 说明 |
|---|---|
| `scripts/capture_voice_chime_quotes.py`（新） | 台词 / 歌词一节中 / 英截图（临时目录、`USERPROFILE=C:\Users\me`）。 |
| `docs/screenshots/voice-chime-quotes-2026-10-21/*.png` | 2 张。 |

## 三、实现要点

- **「没改过」存空串**而不是把内置库整份写进 config：这样代码里以后增删句子，没动过内置库的用户自动跟上；改过的用户以自己的为准（这是他们的选择）。
- **追加去重**只针对和内置完全相同的行；两份库（中 / 英）按音色前缀分开，互不影响（沿用原规则）。
- `clean_custom_quotes` 复用在内置库编辑框上：去空行 / 去重 / 控制字符 / 单条 120 字截断。
- 设置页只用 `QPlainTextEdit` + `QPushButton`，样式沿用页面样式表；编辑框 120～220 px 高、自带滚动。

## 四、性能分析

| 指标 | 实测 / 说明 |
|---|---|
| 报时路径 | `quote_pool` 每次报时拼一次 120 + N 条的元组（微秒级，每小时一次）；原来也是拿同样大小的元组洗牌 |
| 设置页 | 多两个 ~120 行的编辑框（构造时 `setPlainText` 一次）；页面打开实测无可感知变化 |
| 配置文件 | 没改过时多两个空串键；改过时多一份库文本（约 4～5 KB） |
| 新测试 | 6 例 0.2 s；相关族 329 例 20 s |

## 五、实机运行记录

- **红灯**：`tests/test_voice_chime_builtin_quotes.py` 实现前 6 例全红（新键 / `quote_pool` / 页面控件不存在）；
  `tests/test_voice_chime.py` 改成追加语义后 4 例红、`test_menu_layout.py` 行数 1 例红；实现后全绿。
- **截图**：`QT_QPA_PLATFORM=windows python scripts/capture_voice_chime_quotes.py docs/screenshots/voice-chime-quotes-2026-10-21 [--language en]`
  → 中 / 英各一张：内置中文库从「生活就像一盒巧克力……」起预填、「恢复内置」置灰、自定义框里的两句样例、内置英文库从
  "Life was like a box of chocolates" 起、英文版 Restore built-in。
- **肥鱼已重启**（`pet-overlay-gate.log`：`16:04:04 acquired pid=37760`），日志无 Traceback；用户机器上报时开着（整点、晓伊），
  下一个整点按新规则取句（内置 120 条 + 自定义 0 条 = 和改动前同一个库，排列不变）。设置窗口是独立进程，要关掉重开才看到新的两个编辑框。
- 截图与测试里的台词都是内置库原文或中性样例，不含私人内容。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `ruff check pet tests scripts` | All checks passed |
| 聚焦 + 相关 | `pytest -q tests/test_voice_chime_builtin_quotes.py tests/test_voice_chime.py tests/test_config_schema.py tests/test_i18n.py tests/test_settings_english.py tests/test_voice_chime_service.py tests/test_menu_layout.py tests/test_settings_process_isolation.py` | 334 通过 |
| 全量 | `APPDATA=<临时> QT_QPA_PLATFORM=offscreen pytest -q -p no:cacheprovider tests` | 见下（新增持久设置 + 改共享配置键，按 AGENTS.md 要跑全量） |

全量结果：**5 failed, 5549 passed, 11 skipped，527.3 s**——5 个失败全是本机既有的环境性基线（图片选择器路径超 260、两个 cp1252 子进程输出、多显示器负原点、从 Git Bash 启动时的 `test_catalog_animation_count_guard_survives_optimize`），与本次改动无关。

## 七、已知限制与后续

- 内置库编辑框里一条超过 120 字会被截断（沿用自定义台词的规则）。
- 库里句子变了，旧的音频缓存文件不会删（200 个上限自动清理）。
- 节日提醒的台词库仍只在代码里（`festival_quotes*.py`），没有一起做成可编辑。

## 八、风险与回滚

- `git revert` 即可；两个新键留在 config.json 里不碍事（旧版本会忽略）。
- 回滚后自定义台词又变回「替换」语义——回滚时提醒用户。
