# PR 报告：工作笔记进设置页（带流程解释图标）、每条笔记的模型与 token、「记下」按钮对齐

> **基线**：`30ac38f`（style(briefing): 去掉文件末尾多出的空行）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-15
> **范围**：18 个文件（实现 7、测试 3、脚本 2、文档 / 截图）
> **关联**：[`PR-REPORT-WORK-NOTES-2026-10-15.md`](PR-REPORT-WORK-NOTES-2026-10-15.md)、
> [`PR-REPORT-BRIEFING-METRO-2026-10-15.md`](PR-REPORT-BRIEFING-METRO-2026-10-15.md)

## 一、核心特性

用户 2026-10-15 看了 Metro 版简报窗口后的三条：「记下」按钮没对齐，要和输入框一样高；每条笔记能不能
看到用了多少 token、哪个模型；然后做设置页。设置页的要求（之前点名）：要带解释——一个浮动的流程图标，
鼠标放上去就讲清楚这条流程，防止日久忘了细节。新功能一律中英文。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 「记下」按钮 | 和输入框同高（`INPUT_HEIGHT = 72`），不再贴着底边只有一行高。 |
| 2 | 每条笔记的用量 | `claude -p --output-format json` 的结果记录带 `modelUsage`（每个模型的 inputTokens / outputTokens / cacheRead / cacheCreation / costUSD）和 `total_cost_usd`（2026-10-15 探针核实）。总结时取出来写进 frontmatter（`model` / `tokens_in` / `tokens_out` / `cost_usd` / `seconds`），全文的元信息行多一行：`claude-sonnet-5-5 · 输入 35,435 / 输出 656 tokens · $0.038 · 9 秒`。没总结过的笔记不写这些字段。 |
| 3 | 设置页「工作笔记」一节 | 在「自动化与联动」里、「Slack 关注」之后：**流程图标**（`TiltButton` + `automation` 矢量记号，悬停弹出 5 步流程的富文本说明，读屏同样拿得到）、启用开关（没 WSL 置灰并说明）、仓库副本目录、模型（Sonnet / Haiku / Opus / 自定义）。保存走 `work_notes.normalize`，怪模型名、空目录退回默认。 |
| 4 | 中英文 | 用量行与设置页一节共 14 个键进 `pet/locale`。 |

**红线 / 不变量**：`work_notes` 键的三个字段不变（`enabled` / `repo_dir` / `model`）；设置页是它唯一的归属
（`SETTINGS-CHANGE-GATES`：一个偏好一个归属，简报窗口只是消费者）；笔记文件多出的 5 个字段都是可选的，老
文件照常读。

## 二、修改文件说明

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/work_notes.py` | +56 / −4 | `Note` 加 `model` / `tokens_in` / `tokens_out` / `cost_usd` / `seconds`，frontmatter 写读（`_int` / `_float` 容错）；`SummaryResult` 同样加字段；`usage_of(record)` 从 `modelUsage` 汇总（多模型用 `+` 连），没有就退回 `usage`；`parse_summary` / `apply_summary` 带上。 |
| `pet/work_notes_ui.py` | +8 / −2 | `INPUT_HEIGHT` 同时给输入框与按钮；全文多一行用量（`notes.detail.usage`）。 |
| `pet/settings_work_notes.py` | +112 / −0 | 新模块：`flow_button`（流程图标 + 富文本 tooltip + 无障碍描述）、`work_notes_rows`、`save_work_notes_settings`、`chosen_model`；照 `settings_slack_watch.py` 的形状。 |
| `pet/modern_settings_dialog.py` | +4 / −1 | 「自动化与联动」第 4 节挂上；保存时调用。 |
| `pet/locale/zh.json`、`pet/locale/en.json` | +15 / −1、+15 / −1 | `notes.detail.usage`、`notes.settings.*` 共 14 个键。 |
| `scripts/capture_work_notes_settings.py` | +82 / −0 | 把这一节（含 tooltip 文字）在明 / 暗 × 中 / 英渲染成 PNG。 |
| `scripts/capture_briefing_window.py` | +3 / −1 | 样例笔记带上模型与 token，截图里能看到用量行。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_settings_work_notes.py` | +126 / −0 | 行都在「自动化与联动」且显示已存的值；流程图标是磁贴、有图标、tooltip 含 5 步 / 只读 / Obsidian / AI-Base-Memory / token，无障碍描述同一段；改了能经 `normalize` 存回（自定义模型、怪名字退回、空目录退回）；没 WSL 置灰并说明；英文。 |
| `tests/test_work_notes.py` | +21 / −0 | `parse_summary` 从 `modelUsage` / `total_cost_usd` 取模型、token、费用；`apply_summary` → `render` → `parse` 往返；没总结过的不写用量字段；没 `modelUsage` 退回 `usage`。 |
| `tests/test_work_notes_ui.py` | 0 | 既有用例不动即过。 |

## 三、实现要点

- **用量字段从哪来**：探针 `claude_json_keys.py` 跑了一次最小调用，结果记录的键有 `usage`、`modelUsage`、
  `total_cost_usd`、`duration_ms` 等；`modelUsage` 按模型分组、带 `costUSD`。输入 token 按
  `inputTokens + cacheReadInputTokens + cacheCreationInputTokens` 算（缓存读也是算钱的输入）。
- **流程图标**：`vector_menu_icon(button, "automation", 18)` 画在 `TiltButton` 上（它需要一个 widget 取
  DPR 与调色板，传按钮自己）；tooltip 是富文本，Qt 自动按富文本渲染；`accessibleDescription` 放同一段。
- **设置页的截图**：整页截图里这一节在首屏之下，所以单独写了一个脚本抓这一节，并把 tooltip 文字画在下面。

## 四、性能分析

**方法**：这一轮不触动常驻路径。用量字段的解析是在总结结果回来时顺带做的（一次 dict 遍历）；设置页多一节
是打开设置窗口时建 5 行控件。

| 指标 | 实测 | 归属 |
|---|---|---|
| `usage_of(record)` | 一次 dict 遍历，微秒级 | 每次总结 1 次 |
| frontmatter 多 5 行 | 每个文件约 90 字节 | 每次写笔记 1 次 |
| 设置页多一节 | 5 个 `SettingRow`（和 Slack 关注那节同量级） | 打开设置窗口 1 次 |

**结论**：① 稳态零开销；② 新增路径只在总结回来 / 打开设置时各跑一次；③ 无新系统调用、网络、线程
（设置窗口本就是独立进程）；④ 内存：笔记多 5 个字段。

## 五、实机运行记录

```
# 探针：claude -p 结果记录的字段（最小调用，1 轮）
keys: [... 'modelUsage', 'num_turns', ..., 'total_cost_usd', 'usage', ...]
modelUsage = {"claude-sonnet-5-5": {"inputTokens": 2, "outputTokens": 4, "cacheReadInputTokens": 28278,
               "cacheCreationInputTokens": 6361, "costUSD": 0.0283158, ...}}
total_cost_usd = 0.0283158

# 把第一条测试笔记（纯文本）重新总结一次，frontmatter 多出：
ok=True seconds=8.9 turns=1 denied=[] error=''
model: claude-sonnet-5-5
tokens_in: 35435
tokens_out: 656
cost_usd: 0.038012
seconds: 8.9
sync: True
```

- 截图（`QT_QPA_PLATFORM=windows`，真实字体）：`docs/screenshots/briefing-metro-2026-10-15/notes-*.png` 重抓，
  「记下」按钮与输入框同高、全文多出用量行；`docs/screenshots/work-notes-settings-2026-10-15/` 4 张：
  流程图标、开关、目录、模型，下方附 tooltip 全文，明 / 暗 × 中 / 英，逐张看过。
- 肥鱼已重启（`acquired pid=53084`，日志无 Traceback）。设置页是独立进程，用户下次打开设置就能看到这一节；
  本机没有能点真实窗口的自动化工具。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `ruff check pet tests scripts` | All checks passed |
| 聚焦 + 相关 | `pytest -q tests/test_work_notes.py tests/test_work_notes_ui.py tests/test_settings_work_notes.py tests/test_settings_slack_watch.py tests/test_i18n.py tests/test_briefing_metro.py tests/test_settings_metro.py` | 90 通过 |
| 全量 | `python -m pytest -q -p no:cacheprovider`（offscreen，临时 APPDATA） | `4 failed, 5356 passed, 11 skipped in 442.54s (0:07:22)`。4 个失败全是本机既有的环境性基线（`test_image_directory_picker_…` 路径超 260；`test_festival_id_guard_survives_optimize` 与 `test_real_second_process_refused_on_overlay_topology` 子进程输出按 cp1252 解码；`test_capture_window_rect_coordinates_and_clamping` 多显示器负原点），与前几个 PR 的全量同一组。 |

## 七、已知限制与后续

- 用量只有新总结的笔记才有；老笔记点「重新总结」即补上。
- 费用按 Claude Code 自己报的 `total_cost_usd`（按标价算），公司席位实际是订阅，这个数只作参考。
- 仓库目录字段没有「选择…」按钮（Windows 路径手填），需要的话照 VS Code 工作区那一节加。

## 八、风险与回滚

- 无配置迁移；`git revert` 即可。笔记文件里多出的字段对旧版本只是未知的 frontmatter 键，读不坏。

---

## 第二轮：流程说明改成折叠节、菜单入口上提一层、笔记可删

### 现场（用户 2026-10-15 看了第一版之后）

1. 悬停在流程图标上弹出的 tooltip **没有排版**（Qt 的 tooltip 把 `<b>` / `<br>` 当了纯文本）→ 改成设置页里
   「这个功能怎么运作」**折叠节**（默认收起，展开是一块带排版的说明磁贴）。
2. 右键菜单 Agent 联动 → 工作简报 → 工作笔记 **太深** → 「工作笔记」直接放在 Agent 联动 这一层。
3. 笔记要能**删除**。

### 改动

| 文件 | 增删 | 改动 |
|---|---|---|
| `pet/settings_work_notes.py` | +19 / −22 | 去掉流程图标；`flow_section()`：`SettingsSection(advanced=True)`（默认收起的折叠头）+ 一行，说明文字放在行的提示标签（`settingHint`）里，设成富文本、可选中；一个 0×0 的占位控件填控件格。 |
| `pet/modern_settings_dialog.py` | +1 / −0 | 「自动化与联动」第 5 节挂上折叠节。 |
| `pet/context_menus/shared.py` | +3 / −2 | 「工作笔记」从 `add_work_briefing_menu` 挪到 `add_agent_link_menu`，排在「工作简报」子菜单之前。 |
| `pet/work_notes_service.py` | +16 / −0 | `delete(name)`：删文件、发 `changed`、推一次（`note: 删除`）。 |
| `pet/work_notes_ui.py` | +33 / −3 | 面板「删除」按钮与 `delete_requested`；控制器 `delete()`：先问（`confirm` 可注入，默认 `QMessageBox.question`），确认才删，冒一句「删掉了」。 |
| `pet/locale/zh.json`、`pet/locale/en.json` | +6 / −2、+6 / −2 | 删除按钮、问询标题 / 正文、删掉了；折叠节行的提示改口。 |
| `scripts/capture_work_notes_settings.py` | +19 / −18 | 抓「工作笔记」两节（设置 + 展开的折叠节），抓之前先切到那一页（没显示过的页不排版，抓出来是空白）。 |
| `tests/test_settings_work_notes.py` | +18 / −11 | 折叠节默认收起、点开展开、说明是富文本含 5 步；英文。 |
| `tests/test_work_notes_ui.py` | +34 / −0 | 菜单入口是 Agent 联动 的直接子项且不在 工作简报 里；删除：拒绝不动、确认后文件没了并推送、列表清空、按钮置灰。 |

### 一个截图抓出来的坑

第一版折叠节的说明文字在截图里是空白：我给提示标签改了 objectName，设置页样式表里 `QLabel#settingHint`
的颜色规则就不再命中，标签退回调色板的 WindowText——在这个对话框里是白色，白字白底。保持
objectName 不动就好。第二个坑：抓一个从没显示过的页，控件没排版，抓出来也是空白——先 `setCurrentIndex`
切过去再抓。

### 实机

- 截图重抓：`docs/screenshots/work-notes-settings-2026-10-15/`（明 / 暗 × 中 / 英，上半是设置节、下半是展开的
  「这个功能怎么运作」，5 步排版可见）；`docs/screenshots/briefing-metro-2026-10-15/notes-*.png`（底部多了「删除」）。
- 肥鱼已重启（`acquired pid=46568`，日志无 Traceback）。右键 Agent 联动 里现在直接有「工作笔记」。
- 门：ruff 全过；`tests/test_settings_work_notes.py tests/test_work_notes_ui.py tests/test_work_notes.py tests/test_i18n.py
  tests/test_sprite_menu_parity.py tests/test_work_briefing.py` 129 通过；全量：`4 failed, 5359 passed, 11 skipped in 443.06s (0:07:23)`，4 个失败是本机既有的环境性基线（同前）。
