# PR 报告：笔记的基本信息挪到底部信息栏，每项配图标（2026-10-20）

> **基线**：`1fa139ed`（fix(settings): island icon applies the moment you pick it）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-20
> **范围**：实现 2（新增 1）、文案 2、测试 2（新增 1）、脚本 1（新增）、文档 2、截图 4
> **关联**：笔记页布局见 `docs/PR-REPORT-WORK-NOTES-LAYOUT-2026-10-16.md`；用量字段的来源见 `docs/PR-REPORT-WORK-NOTES-SETTINGS-2026-10-15.md`。

## 一、核心特性

用户要求：笔记详情里的基本信息（记下的时间、模型、tokens、花费）都是纯文字，要更有表现力，比如花费配一个美元图标；
而且它们不是重点，放到底部去。

以前正文第二、三行是：

```
记于 10-20 15:38 · jira · 提醒 10-23 09:30 · `jira`
claude-sonnet-5-5 · 输入 150,123 / 输出 1,612 tokens · $0.145 · 19 秒
```

| # | 能力 | 说明 |
|---|---|---|
| 1 | 底部信息栏 | 详情下面一条不随正文滚动的细栏，背景同详情卡片，顶上一道细分隔线。 |
| 2 | 每项一个图标 | 时钟 = 记下的时间、四角火花 = 模型、托盘 + 向下箭头 = 输入 tokens、托盘 + 向上箭头 = 输出 tokens、**美元硬币 = 花费**、秒表 = 用时。线条图标自己画，颜色用次要文字色。 |
| 3 | 数字简短 | tokens 缩写成 `34.6k` / `1.2M`；花费三位小数（`<0.001`、≥1 两位）；用时取整秒。 |
| 4 | 精确值在悬停里 | 「输入 34,641 tokens」「这次总结花了 $0.0283（Claude Code 报的）」「Claude Code 读了 9.7 秒」；整条的读屏名字是全部精确值。 |
| 5 | 正文只留要看的 | 标题、类型、提醒 / 完成、标签、摘要、原文。 |
| 6 | 没有的就不显示 | 没总结过的笔记（和 Slack 关注页的条目）只有时间那一项；没选中笔记时整条不出现。 |
| 7 | 跟主题、跟语言 | 白天 / 黑夜切换时图标换色；中英文。「笔记」页和「Slack 关注」页是同一个面板，都有。 |

**红线 / 不变量**：笔记文件格式不变（用量字段照旧写在 front matter）；列表、按钮、提醒、推送都不动；不画 emoji（首次画 emoji 加载彩色字体栈约 +33 MB）。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/note_meta_bar.py` | 新增 181 行 | `NoteMetaBar(QFrame)`：六个 `_Chip`（图标 QLabel + 文字 QLabel，文字按纯文本显示，模型名是外来内容），`show_note(note \| None)` 填值 / 隐藏、设悬停与读屏名字；`apply_colors` 换色板后重画图标并重设样式。`meta_icon(name, color, size, dpr)` 在 16 单位画布上画六个线条图标（美元硬币是圆 + 粗体「$」）。`short_count` / `short_cost` 两个格式化函数。 |
| `pet/work_notes_ui.py` | +19 / −7 | `detail_markdown` 去掉「记于 …」和用量那一行；详情右侧改成 `detail_pane`（详情 + `meta_bar` 竖排，间距 0），分隔条右边放它；`_show_current` 每次选中都 `meta_bar.show_note`；`apply_theme` 同步给信息栏换色。 |
| `pet/locale/zh.json`、`en.json` | 各 +7 / −2 | 新增 `notes.meta.*` 7 条（6 条悬停 + 「{n} 秒」）；删掉不再用的 `notes.detail.created` 与 `notes.detail.usage`。 |

### 测试

| 文件 | 覆盖 |
|---|---|
| `tests/test_note_meta_bar.py`（新增，18 个用例） | 正文不再有时间 / 模型 / tokens / 花费；总结过的笔记六项齐、顺序对、六个图标两两不同、信息栏在详情下面；悬停精确值与读屏名字；没总结过只有时间；没选中整条隐藏；tokens 缩写 6 档、花费 4 档；黑夜图标更浅；英文；Slack 页同样有。 |
| `tests/test_work_notes_ui.py` | +3 / −1：分隔条右边现在是 `detail_pane`（里面有详情和信息栏）。 |

### 脚本与文档

| 文件 | 说明 |
|---|---|
| `scripts/capture_note_meta_bar.py`（新增） | 用中性样例笔记把「笔记」页在白天 / 黑夜 × 中 / 英各渲染一张；不碰真实数据目录。 |
| `docs/screenshots/note-meta-bar-2026-10-20/` | 4 张截图（`QT_QPA_PLATFORM=windows`，真实字体）。 |
| `docs/PR-REPORT-NOTE-META-BAR-2026-10-20.md`、`docs/INDEX.md` | 本报告与登记。 |

## 三、实现要点

- **为什么是单独一条控件而不是写进 Markdown**：`QTextBrowser` 的 Markdown 放不了跟主题变色的小图标，而且放在正文里就会跟着长原文滚走。单独一条放在详情下面，「不是重点」也「随时看得到」。
- **图标自己画**：与灵动岛 / 菜单的线条图标同一画法（16 单位画布、圆头 1.5 笔宽），颜色用色板的 `muted`；`apply_colors` 时重画。
- **只在数据里有的时候显示**：判断条件和以前一样是 `note.model`——总结过才有模型和用量。

## 四、性能分析

**方法**：`QT_QPA_PLATFORM=windows` 下在本机直接计时（5 组取中位数）。环境：Windows 11 Pro 26300，Python 3.13.15，PySide6（仓库 `.venv`）。

| 指标 | 实测 | 归属 / 频率 |
|---|---|---|
| `NoteMetaBar.show_note` | 18.6 µs / 次（5 × 500） | 新增；每次选中一条笔记一次 |
| 面板整次选中刷新 `_show_current`（含 Markdown 排版） | 123.8 µs / 次（5 × 200） | 既有路径，信息栏占其中约 15% |
| `apply_colors`（重画 6 个图标 + 样式表） | 1.07 ms / 次（5 × 200） | 新增；只在白天 / 黑夜切换时一次 |

**结论**：① 稳态没有开销：信息栏没有定时器、不重绘就不花钱。② 新增路径：选中一条 +18.6 µs；换主题 +1 ms。③ 没有新的系统调用、网络、磁盘、线程。④ 内存：每个面板多 6 张 14×14（×DPR）的小图和 13 个标签，量级 KB。

## 五、实机运行记录

- **截图**（本机真实字体）：`docs/screenshots/note-meta-bar-2026-10-20/notes-meta-{light,dark}-{zh,en}.png`。正文从标题直接到摘要；底部一条：时钟 `10-20 15:41`、火花 `claude-sonnet-5-5`、↓ `34.6k`、↑ `412`、美元硬币 `0.028`、秒表 `19 s` / `19 秒`。四张都检查过没有截字。
- **用户的真实笔记**（只打印条数和数字，不打印内容；笔记里是工作内容）：

  ```
  note notes: 6 {'with_usage': 4, 'time_only': 2} | e.g. ['10-20 15:38', '150k', '1.6k', '0.145', '19 s']
  slack notes: 4 {'with_usage': 0, 'time_only': 4}
  ```

  六条工作笔记里四条总结过、六项齐；两条没总结过、只显示时间。Slack 关注的四条不带用量字段，只显示时间——符合设计。
- **重启桌宠**：17:13 结束 pid 43636、用 `run.bat` 重启，`pet-overlay-gate.log` 新增 `acquired pid=46944`，新日志无 Traceback / ERROR。简报窗口是点了才建的，下次打开「笔记」页就是新样子。
- **没能自动做的**：在真桌宠里点开简报窗口看一眼——那要点灵动岛上的图标，我这边没有能点它的工具。截图用的是同一个窗口类和同一套样式表。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests scripts/capture_note_meta_bar.py` | All checks passed |
| 红→绿 | 先写 `tests/test_note_meta_bar.py`，改实现前收集即失败（模块不存在）；改后 18 过 | ✔ |
| 相关 | `test_note_meta_bar / test_work_notes_ui / test_work_notes / test_slack_notes / test_work_briefing / test_work_briefing_links_and_island / test_work_notes_push_status / test_i18n / test_rest_english / test_architecture` | 169 passed |
| 受影响时序族 | 不涉及线程 / 事件循环时序 | 豁免 |
| 全量 | 隔离 worktree，`-X faulthandler`，临时 `APPDATA` | 见下 |

全量结果：`4 failed, 5542 passed, 11 skipped in 534.78s (0:08:54)`（隔离 worktree，HEAD `1fa139ed` + 本改动）。4 个失败是本机既有的环境性基线（路径超 260 / 子进程 cp1252 解码 ×2 / 多显示器负原点），与前几轮相同，没有原生崩溃。

## 七、已知限制与后续

- 标题下那一行里，类型和标签常常是同一个词（`jira · … · jira`），这是之前就有的；没在这次动。
- 浅色主题下原文里的链接颜色偏粉，也是之前就有的样子，没在这次动。

## 八、风险与回滚

- 只动展示；笔记文件、配置都不变。回滚：`git revert`。
