# 会话记忆蒸馏·第三期（二）：公司侧候选只交给 WSL 里的公司账号蒸馏

> **基线**：main（第三期（一）WSL 抽取合并之后）
> **分支**：`feature/memory-distill-work-channel`　**日期**：2026-11-10
> **范围**：11 个文件（实现 5、文案 2、测试 2、文档 1 + 索引）
> **关联**：[`PR-REPORT-MEMORY-DISTILL-WSL-EXTRACT-2026-11-10.md`](PR-REPORT-MEMORY-DISTILL-WSL-EXTRACT-2026-11-10.md)、
> [`PR-REPORT-MEMORY-DISTILL-PHASE2-2026-10-31.md`](PR-REPORT-MEMORY-DISTILL-PHASE2-2026-10-31.md)（个人侧蒸馏）

## 一、核心特性

公司侧候选（WSL 里的会话、公司目录下的会话）此前只入库、从不蒸馏。按 10-30 的定案，它们**不能**发给个人 key
（「AI 对话」里的服务商）：公司会话的原话不进个人账号。本 PR 给公司侧接一条自己的蒸馏通道。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 公司侧走 WSL 里的公司账号 | `wsl.exe -e bash -lc "claude -p …"`，提示词走标准输入；不给任何工具、一轮、不留会话记录 |
| 2 | 现有记忆读 WSL 那份 | WSL 里的 `~/.claude/CLAUDE.md` 与候选涉及项目的 `memory/MEMORY.md`，一次 `wsl.exe` 读完 |
| 3 | 两侧互不相见 | 提案带 `side`；「别再提」名单、已落盘条目、状态文件（`distill-state-work.json`）都按侧分 |
| 4 | 设置明文、与个人侧分开 | 公司侧每日蒸馏开关、时刻、模型（Claude Code 别名）、强度、提示词，各存各的（`work_*`） |
| 5 | 两侧可以同时跑 | 每侧一个「忙」标记；顺带修了交叠运行时结果被当成过期丢掉的潜伏问题（见第三节） |

**红线 / 不变量**：公司侧的任何文字（候选、现有记忆、拒过的标题、提案）不出现在发给个人 key 的提示词里——
`test_work_distill_goes_through_wsl_and_never_reaches_the_personal_key` 用「个人 key 替身收到的每份提示词」逐个断言；
个人侧的行为、提案 id、状态文件不变；仍是全人工审核。**接受公司侧提案在本 PR 里被拒绝**（落点在 WSL 里，下一个
PR 才接），绝不会写到个人侧的 `CLAUDE.md` / 项目 memory / 个人知识库。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/memory_distill_wsl.py` | +144 / −2 | `claude_command`（无工具、`--max-turns 1`、`--no-session-persistence`、`CLAUDE_CODE_MAX_OUTPUT_TOKENS`、模型 / 强度经 `work_briefing` 的两个 normalize 才拼进 shell）；`make_complete(runner)` 返回与个人侧 `complete` 同签名的函数，解析 `claude -p` 的结果 JSON（复用 `work_briefing._result_record` / `work_notes.usage_of`），失败一律抛 `WslError`；`read_files` / `memory_context`（一次 `sh -c` 读多个文件，按标记行切开） |
| `pet/memory_distill_run.py` | +37 / −17 | `Proposal.side`、`RunResult.side`；`proposal_id(..., side)`（个人侧算法不变，公司侧多掺侧名）；`parse_proposals(side=)`；`ProposalStore.dismissed_titles(side)`；`load_state` / `save_state` 按侧分文件；`run_once(side=, memory_fn=)`，`provider` 可为 `None` |
| `pet/memory_distill.py` | +24 | 配置 `work_distill` / `work_daily_at` / `work_model` / `work_effort` / `work_prompt_zh|en`；`side_settings(settings, side)` 把公司侧那几项换到通用键上，`run_once` 因此不用分侧 |
| `pet/memory_distill_service.py` | +62 / −42 | `distill_now(manual, side)`：公司侧用 `mdw.make_complete` + `mdw.memory_context`，不解析个人服务商；`_distilling` 改成按侧的集合；`check()` 两侧各按各的时刻；`stats()["distill_work"]`；`review()` 对公司侧提案的「接受」返回错误并留在待审；`_generation` 只在 `stop()` 时递增 |
| `pet/settings_memory_distill.py` | +63 | `_work_rows`：6 个设置行（开关 / 时刻 / 模型下拉 + 自定义 / 强度 / 提示词编辑器），保存进 `work_*` |
| `pet/locale/zh.json`、`pet/locale/en.json` | 各 +18 / −1 | 17 条新文案 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_memory_distill_work.py`（新增） | +349 | 命令形状与注入防护；结果解析与四种失败；WSL 记忆一次读完；`run_once` 按侧（候选、拒过的标题、提案 id、状态文件）；设置默认值 / 归一化 / 页面往返；服务：公司侧不调个人 key、个人提示词里没有公司侧的字、失败只记在公司侧、两侧各按各的时刻、公司侧可关、三个后台任务交叠不丢结果、接受公司侧提案被拒且不写个人侧文件 |
| `tests/test_memory_distill_ui.py` | +2 / −1 | 设置行顺序加公司侧 6 行 |

### 未改动

`memory_distill_sink.py`（公司侧落盘是下一个 PR）、`memory_distill_ui.py`（页面按侧显示与「总结公司侧」按钮同在下一个 PR；
本 PR 之后公司侧蒸馏只能由每日定时触发或代码调用）。`chat/anthropic_provider.py` 没有动——公司侧根本不经过它。

## 三、实现要点

- **通道隔离放在「谁来 complete」而不是「过滤内容」**：`run_once` 对两侧是同一段代码，差别全在调用方注入的三样东西——
  `complete`、`memory_fn`、`settings`。公司侧分支里没有任何拿到个人服务商的路径（`provider=None`）。
- **`--no-session-persistence`**：不然这次 `claude -p` 自己会在 WSL 的 `~/.claude/projects` 留一份 transcript，里面的
  「用户消息」就是整份提示词（150 条候选原话），下一轮抽取会把它当成「我说过的话」抽回来。
- **`--tools ''` + `--max-turns 1`**：这一步只要模型读提示词、写 JSON；不给工具也就不存在它去读写别的东西的可能。
- **模型名 / 强度会拼进 shell**：都先过 `work_briefing.normalize_model` / `normalize_effort`（只认字母数字和 `. _ -` /
  四档），不合法退回默认；提示词走标准输入，不进命令行。
- **`_generation` 的修正**：原来抽取、蒸馏、推送每次启动都把同一个 `_generation` 加一，回调里「不等于当前值就丢」。
  真机上两个后台任务一旦交叠（每日时刻那次 `check()` 先起抽取线程、紧接着起蒸馏线程），先起的那个结果就被丢、
  它的「忙」标记永远不清。测试里线程是同步替身所以没暴露。现在只有 `stop()` 递增。红测试：
  `test_both_sides_and_an_extraction_can_overlap_without_losing_anyones_result`（旧写法下三个结果只回来一个）。
- **取舍**：公司侧默认模型用 Claude Code 的 `sonnet` 别名（和工作简报 / 笔记一致），没有照个人侧「跟 AI 对话一致」；
  `claude -p` 会带上 Claude Code 自己的系统提示词与 WSL 里的 `CLAUDE.md`（实测每次约 9 万 token 的缓存写入），
  这部分开销换来的是凭证不出 WSL。

## 四、性能分析

**方法**：`scratchpad/real_work_distill.py` 对候选库**副本**（含上一步抽进来的公司侧候选）跑一次真实
`wsl.exe` + 真实 `claude -p`（公司账号）。环境：Windows 11、Python 3.13、WSL2 Ubuntu 24.04、Claude Code 2.1.319。
样本量 1 次（每次是一次真实的计费调用，没有多跑）。

| 指标 | 实测 | 归属 |
|---|---|---|
| 读 WSL 里的现有记忆（1 个 CLAUDE.md + 8 个项目索引） | 110 ms，13,937 字符 | 新增，每次公司侧蒸馏一次 |
| 提示词 | 90,214 字符（150 条候选） | 新增 |
| `claude -p`（sonnet / high） | 84.6 s，输入 135,403 token（含缓存读写）、输出 10,504 token | 新增，每日一次 + 手动 |
| 最小调用（`haiku` / low，回 `[]`） | 5.6 s，缓存写入 91,294 token | 通道固定开销 |
| 结果 | 150 条候选 → 8 条提案，丢项 0，未截断 | — |

**结论**：① 不蒸馏时没有任何新增稳态开销（`check()` 每小时多读一个状态文件）。② 新路径每天最多自动跑一次，每次
一两分钟，全在后台线程；用量算在公司席位上。③ 新增系统调用：每次蒸馏两次 `wsl.exe` 子进程（读记忆、`claude -p`）；
网络由 WSL 里的 Claude Code 自己发，肥鱼进程不发；磁盘多一个 `distill-state-work.json`。④ 内存：候选库整份读入
（与个人侧相同），提示词 90 KB。

## 五、实机运行记录

- **前提**：真实候选库里公司侧候选此前从未被蒸馏（`distill-state-work.json` 不存在；提案库里没有公司侧提案）。
- **实机输出**（2026-11-10，对副本跑；只有计数与结构）：

  ```
  work candidates since last run: 867 -> picked 150 Counter({'rule': 52, 'correction': 50, 'decision': 40, 'task': 8})
  memory context: 13937 chars, 9 sections, 110 ms
  prompt chars: 90214
  ok=True error='' candidates=150 proposals=8 added=8 dropped=0 resend=False truncated=False
  model=claude-sonnet-5-5 effort=high tokens_in=135403 tokens_out=10504 seconds=84.6
  work proposals: 8 Counter({('add', 'global'): 6, ('change', 'global'): 1, ('add', 'project'): 1})
  personal-side proposals untouched: 9
  state files: ['distill-state-work.json', 'distill-state.json']
  ```

- **验收用例**：用户在 WSL 的 Claude 里说过的那条英文文档写作规范，在公司侧提案里**命中 1 条**（全局）。原文不入报告。
- **「丢项」修复的真实输出**：这次真实模型输出经过新的逐项解析，`dropped=0`。
- **为什么对副本跑**：此刻正在跑的桌宠是旧代码，它的「接受」会把任何提案写进个人侧的 `CLAUDE.md` 与个人知识库；
  公司侧提案要等桌宠换上带保护的代码之后才能进真实提案库。真实库上的那一次随第三期最后一个 PR 的重启记录补。
- **没有自动验证的**：个人 key 一侧没有实机调用（本 PR 不改个人侧的调用路径，隔离由替身逐字断言）。

## 六、测试与验证

- **红 → 绿**：`tests/test_memory_distill_work.py` 先写；`_generation` 那条在恢复旧写法时实测失败
  （`assert ['personal'] == ['work', 'refresh', 'personal']`）。
- `ruff check pet tests`：All checks passed。蒸馏族 7 个文件 + i18n + 架构：148 passed。
- 设置变更门禁：6 个新键都有安全默认（公司侧没有候选时不会调用模型；没有 WSL 时失败只记在公司侧状态里）、旧配置
  无需迁移、保存语义与本节其他项相同（设置窗口保存时写入）。
- 全量 pytest：见 PR 描述。

## 七、已知限制与后续

- 每次最多送 150 条候选（超了先丢「任务」）；本机首轮有 867 条，剩下的不会再送——游标按时间推到最新。
- 页面上还没有「总结公司侧」按钮、提案不标侧、公司侧提案接受不了：下一个 PR。
- 公司侧知识库镜像（`AI-Base-Memory`）：再下一个 PR。
