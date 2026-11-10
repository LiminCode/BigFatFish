# 会话记忆蒸馏第二期：补进 main，并修「审核时改了标题，作废 / 修改找不到旧条目」

> **基线**：`48c6d60d`（main，会话小鱼记住 VS Code 工作区合并后）
> **分支**：`feature/memory-distill-phase2-land`　**日期**：`2026-11-10`
> **范围**：17 个文件（实现 10、测试 4、文档 3）
> **关联**：[`PR-REPORT-MEMORY-DISTILL-PHASE2-2026-10-31.md`](PR-REPORT-MEMORY-DISTILL-PHASE2-2026-10-31.md)（第二期原报告，随本 PR 一起进 main）、
> [`PR-REPORT-MEMORY-DISTILL-PHASE1-2026-10-31.md`](PR-REPORT-MEMORY-DISTILL-PHASE1-2026-10-31.md)、
> [`PR-MERGE-LESSONS-2026-09-12.md`](PR-MERGE-LESSONS-2026-09-12.md)（叠放 PR 的教训）

## 一、核心特性

**第二期其实一直没进 main。** 第二期 PR #10 叠放在第一期 PR #9 的分支上（base = `feature/claude-session-fish`）。
2026-10-31 20:57:56 #9 squash 进 main（`ca960cdf`），9 秒后 20:58:05 #10 被合并——合进的是 #9 的**旧分支**
（`d3c79e81`），不是 main。结果 main 上只有抽取 + 候选库 + 流程页骨架，「现在总结」、提案页、落盘、知识库镜像全都没有。
核对方法：`git merge-base --is-ancestor d3c79e81 origin/main` 返回非 0；`pet/memory_distill_run.py` /
`pet/memory_distill_sink.py` 在 main 上不存在。

本 PR 做两件事：

1. **把 `d3c79e81` 原样挑到 main 上**（`72c3d304`）。唯一冲突是 `docs/INDEX.md` 的报告登记表（冲突块里 main 一侧有 15 行后来登记的报告），
   解法是保留 main 的全部行、加上第二期那一行。代码文件零冲突。挑的是 squash 提交，它和第二期分支尖 `807541af`
   的 `pet/`、`tests/` 完全相同（`git diff d3c79e81 807541af -- pet tests` 为空），没有漏掉分支上后来的提交。
2. **修一个第二期原报告里记着「实机还没跑」的分支上的 bug**（`131dad53`）：审核一条 `retire`（或没写 `replaces` 的
   `change`）提案时如果改了标题，落盘按改后的标题去条目库找旧条目，找不到，报「没找到要作废 / 修改的条目」，提案留在待审里
   永远接受不了。现在改标题前先把原标题记进 `replaces`。

## 二、修改文件说明

增删行数取自 `git diff --numstat origin/main HEAD`（合计 +2838 / −65，不含本报告及其索引登记行）。

### 实现

| 文件 | +/− | 改了什么 | 为什么 |
|---|---|---|---|
| `pet/memory_distill_run.py`（新增） | +457 | 蒸馏：到点判定、挑个人侧候选（超预算先丢任务指令）、读现有记忆、拼提示词、解析提案（截断抢救）、提案库 | 第二期核心，原样来自 `d3c79e81` |
| `pet/memory_distill_sink.py`（新增） | +355 | 落盘：条目库 `entries.json`、`CLAUDE.md` 受管块（改前备份）、项目 `memory/distill-<id>.md` + `MEMORY.md` 索引、知识库那篇整篇重生成 | 同上 |
| `pet/memory_distill_service.py` | +263 / −4 | 每日 / 手动蒸馏、`review()` 接受 / 拒 / 跳过、镜像推送线程；**本次新增 4 行**：改标题前给 `change` / `retire` 补 `replaces` | 前者同上；后者是本次的 bug 修复 |
| `pet/memory_distill_ui.py` | +470 / −44 | 流程页「提案」页（逐条看、改、接受 / 拒 / 跳过）、流程图后三格、Metro 实色磁贴、WSL 入口 | 原样来自 `d3c79e81` |
| `pet/memory_distill.py` | +8 / −1 | 配置节多 `mirror_to_vault`；默认提示词（中 / 英）多一段「之前被我拒掉的提案」`{dismissed}` | 同上；拒过的不再提 |
| `pet/settings_memory_distill.py` | +6 | 设置页多「镜像到知识库」开关 | 同上 |
| `pet/personal_vault.py` | +9 / −3 | 从灵感记录的推送里抽出 `sync_path(仓库, 文件, 提交说明)`（add → 有变化才 commit → pull --rebase → push） | 蒸馏镜像与灵感记录走同一条推送路 |
| `pet/work_briefing.py` | +1 / −1 | `render_template` 的占位符白名单多 `candidates` / `memory` / `dismissed` | 蒸馏提示词复用同一套模板渲染 |
| `pet/locale/zh.json`、`en.json` | 各 +60 / −2 | 提案页、状态、报错文案 | 同上 |

### 测试

| 文件 | +/− | 覆盖 |
|---|---|---|
| `tests/test_memory_distill_run.py`（新增） | +251 | 到点规则、候选挑选与预算、提示词、解析 / 截断抢救、提案库、`run_once` 成功 / 失败 / 截断 |
| `tests/test_memory_distill_sink.py`（新增） | +152 | 条目库 add / change / retire、受管块原位替换、项目文件 + 索引、知识库那篇、一条提案落到所有地方 |
| `tests/test_memory_distill_phase2_ui.py`（新增） | +364 | 服务级蒸馏 / 审核 / 推送、提案页、定时触发；**本次新增 3 条（+69 行）**，见第六节 |
| `tests/test_memory_distill_ui.py` | +161 / −8 | 流程页磁贴、WSL 入口、切语言重建窗口 |

### 文档

| 文件 | +/− | 说明 |
|---|---|---|
| `docs/PR-REPORT-MEMORY-DISTILL-PHASE2-2026-10-31.md`（新增） | +220 | 第二期原报告，随挑拣进 main，内容未改 |
| `docs/PR-REPORT-MEMORY-DISTILL-PHASE2-LAND-2026-11-10.md`（新增） | 本文件 | — |
| `docs/INDEX.md` | +2 | 登记上面两份报告 |

新增文件 7 个（实现 2、测试 3、报告 2）；没有删除文件。

### 未改动

配置结构没有新增键之外的变化：`memory_distill.mirror_to_vault` 在 `d3c79e81` 里就有，`normalize()` 对缺键给默认 `True`，
旧配置文件不需要迁移（本机真实配置里 10-31 起就带着这个键）。设置页的提示词 / 模型 / effort / 每日时刻四项第一期就已明文摆出，
本次没动。`PetWindow`、overlay、碰撞、会话小鱼都没碰。

## 三、实现要点

**为什么会找不到旧条目。** 条目库按标题找旧条目：`EntriesStore.apply()` 里是
`self.find(proposal.replaces or proposal.title, …)`。模型给 `retire` 时通常不写 `replaces`，标题本身就是「指哪条」。
而 `MemoryDistillService.review()` 在调落盘之前先把用户改过的标题写进 `proposal.title`——于是「指哪条」跟着被改掉了。

**修法**（`pet/memory_distill_service.py`，`review()` 内）：

```python
edited = " ".join(title.split())
if edited != proposal.title and proposal.action in ("change", "retire") and not proposal.replaces:
    proposal.replaces = proposal.title     # 没写 replaces 时标题就是「指哪条」；改了措辞也得还指着它
proposal.title = edited
```

只在三个条件同时成立时补：标题确实变了、动作是 `change` / `retire`、模型没给 `replaces`。`add` 不受影响；模型给了
`replaces` 的 `change` 也不受影响（那时改标题本来就是在改新标题）。

**取舍：为什么不在落盘层按 id 找。** 提案 id 是 `(动作, 作用域, 项目, 标题)` 的哈希，和被指的旧条目 id 没有关系，
落盘层拿不到「原本指谁」；这个信息只有审核那一刻（标题被覆盖之前）还在，所以修在服务层。

**没改的行为，值得知道**：`retire` 指向一条不是蒸馏写的记忆（手写的 `CLAUDE.md` 行、手写的 memory 文件）时，条目库里没有它，
接受会报错并留在待审——蒸馏只管自己写进去的条目，不动手写的内容。这条本次补了测试钉住，行为没变。

## 四、性能分析

环境：Windows 11、Python 3.13、PySide6 offscreen，真实 `%APPDATA%\big-fat-fish` 数据（候选 418 条 / 27 天，提案 9 条，
条目 2 条）。命令：`python <scratch>/perf.py`（`time.perf_counter`，逐次计时取中位数与 p95）。**测量时后台正在跑全量
pytest（CPU 打满）**，所以这些是偏悲观的数字。

| 路径 | 实测 | 样本 | 触发频率 |
|---|---|---|---|
| `service.check()`，`enabled=False`（本机现状） | 中位 85.3 µs，p95 104.6 µs | 200 | 每小时一次（`REFRESH_INTERVAL_MS`，第一期就有的定时器，本次没加新定时器） |
| `proposals().pending()`（读 + 解析 `proposals.json`，9 条） | 中位 144.3 µs，p95 164.8 µs | 200 | 开流程页、审一条之后 |
| `service.stats()`（候选库 27 个日文件计数 + 提案 + 条目） | 中位 6.0 ms，p95 6.9 ms | 50 | 开流程页、每次 `changed` 信号 |
| 流程页开窗（真实数据，7 条待审） | 181 ms | 1 | 用户点开时 |
| 接受一条全局提案（条目库 + `CLAUDE.md` 备份 + 原子替换） | 中位 11.2 ms，p95 12.2 ms | 50 | 用户点「接受」时 |
| 增量扫描（真实 transcript 目录，新增 1 条） | 0.20 s | 1 | 手动「扫描」/ 每小时（开着时） |
| 一次真实蒸馏（99 条候选） | 120.2 s，28,103 入 / 10,369 出 token | 1 | 每日一次（开着时）/ 手动 |
| 本次修复新增的开销 | 一次字符串比较 + 至多一次赋值 | — | 只在接受且带改过的标题时 |

逐条回答：

- **稳态开销**：功能关着时（默认、本机现状）每小时一次 `check()`，约 85 µs。开着时多一次增量扫描（0.2 s 量级，在工作线程）
  和每天一次模型调用。
- **新增路径成本与触发频率**：见上表。蒸馏的 120 s 全部在工作线程里等网络，GUI 线程只在完成时收一个信号。
- **新的系统调用 / 网络 / 磁盘 / 线程**（相对 main）：网络——每次蒸馏 1 个模型请求（走「AI 对话」配置的服务商）；接受且镜像
  开着时 1 轮 `git add / commit / pull --rebase / push`（工作线程）。磁盘——`proposals.json`、`entries.json`、
  `distill-state.json`、`backups/CLAUDE.md.*.bak`（每次改 `CLAUDE.md` 前一份）、`~/.claude/CLAUDE.md` 受管块、项目
  `memory/` 下的文件。线程——蒸馏与推送各用一个一次性工作线程，结束即退出；没有常驻线程。
- **内存**：`tracemalloc` 下连续 200 次 `check()` + `pending()` 后堆增长 1,003 字节（不随次数增长：每次都是读文件 → 解析 →
  丢弃，服务不缓存提案列表）。备份目录会随接受次数增长（每份等于当时的 `CLAUDE.md`，本机 1.7 KB），目前没有清理。

## 五、实机运行记录

本机真实环境，2026-11-10。运行中的桌宠全程是 pid 32156（`pet-overlay-gate.log` 最后一行
`2026-11-08 05:34:21 acquired pid=32156`，三次核对未变）；它跑的是 main、没有第二期，所以下面三项是从本分支的工作区直接
起服务对象、读写真实 `%APPDATA%` 完成的，没有重启桌宠。记录里只有计数，不含任何候选 / 提案原文。

**1. 真实蒸馏一次**（真实配置、真实 transcript、真实模型；`python <scratch>/live_distill.py`）：

```
settings: {'enabled': False, 'keep_days': 90, 'work_roots': 1, 'daily_at': '21:30', 'model': '', 'effort': 'high', … 'mirror_to_vault': True}
candidates stats: {'total': 417, 'days': 26}
distill state before: {… 'done_date': '2026-10-31', 'last_run_at': '2026-10-31T11:26:48', …}
proposals before: {'pending': 3, 'accepted': 2, 'rejected': 0, 'skipped': 0, 'total': 5} entries: {'global': 1, 'project': 1, 'retired': 0}
refresh_s: 0.20 candidates after refresh: {'total': 418, 'days': 27}
started: True elapsed_s: 120.3
result: {'ok': True, 'error': '', 'candidates': 99, 'proposals': 4, 'added': 4, 'model': 'claude-sonnet-5', 'effort': 'high', 'tokens_in': 28103, 'tokens_out': 10369, 'seconds': 120.2, 'truncated': False}
proposals after: {'pending': 7, 'accepted': 2, 'rejected': 0, 'skipped': 0, 'total': 9}
pending by action/scope: {('add', 'global'): 1, ('change', 'project'): 3, ('add', 'project'): 3}
```

没有自动接受任何一条：`~/.claude/CLAUDE.md` 与项目 memory 目录在这次运行前后没有变化（设计就是全人工审核）。7 条待审留给
本人在流程页里审。

一个观察：模型这次写了 5 项，入库 4 项。第 5 项的一个字符串里带了没转义的直引号，整段不是合法 JSON，走的是「抢救已完整的
项」那条路——前 4 项保住了，第 5 项丢了，而状态里 `truncated` 是 `False`、没有任何提示。见第七节。

**2. 改写 / 作废命中旧条目**（原报告里「实机还没跑」的两条分支）。这两步会改 `CLAUDE.md`，而接受与否该由本人审，所以在
**真实数据的副本**上跑：把真实 `entries.json` 和真实 `~/.claude/CLAUDE.md` 拷到临时目录，镜像关掉
（`python <scratch>/live_change_retire.py`）：

```
real CLAUDE.md: bytes 1708 crlf 0 block found True
change: {'error': '', 'claude_md': True, 'same_id': True} outside block identical: True bullets in block: 1 new title in: True crlf after 0 backups 1
retire: {'error': '', 'removed': True, 'claude_md': False} files before 2 after ['MEMORY.md'] index lines 0 active 1 retired 1
```

改写：条目 id 不变、受管块里仍是 1 条（不是又添一条）、块外逐字不变、改前留了备份。作废项目条目：`distill-<id>.md` 删掉、
`MEMORY.md` 里那行索引删掉、`CLAUDE.md` 不动。

**3. 流程页对真实数据开窗**（offscreen；`python <scratch>/live_page.py`）：

```
open_ms 181 | tab: 提案 7 | rows: 7
distill => 上次 11-10 13:58 · 4 条提案
review => 待审 7 · 已接受 2 · 已拒 0
sink => 全局 1 条 · 项目 1 条
run_label: 上次总结 2026-11-10 13:58 · claude-sonnet-5 · high · 28,103 → 10,369 tokens · 120 秒 · 99 条候选 → …
```

**没有自动验证的部分与原因**：真机窗口里的点击（托盘 →「会话记忆蒸馏」→ 提案页 → 接受）本轮没做。原因：运行中的桌宠
（pid 32156）是 main 的代码，没有提案页；要点就得先从本分支重启桌宠，而合成点击会和正在用的鼠标叠在一起（11-07 灵动岛那轮
踩过）。同一条链路 10-31 在第二期分支上由本人实机点过两次（全局 1 条、项目 1 条，见原报告），这次代码相对那时只多了 4 行。
合并后从 main 重启桌宠的记录追加在本节末尾。

**追记：合并后从 main 重启**（2026-11-10）。PR #30 squash 为 `0b438914`，主检出快进到它；结束旧进程 pid 32156（没有开着的设置窗口），
从主检出 `BigFish.exe -m pet` 重启：

```
before: 2026-11-08 05:34:21 acquired pid=32156 …
after:  2026-11-10 14:11:03 acquired pid=59480 …
pet-59480.log  WARNING/ERROR lines: 0   「会话记忆蒸馏接线失败」: 0
```

启动 9 秒内日志 0 条 WARNING / ERROR，蒸馏服务接线没有报错。真机窗口里点「接受」仍未做（见上）。

## 六、测试与验证

- **红 → 绿**：`tests/test_memory_distill_phase2_ui.py::test_retire_with_a_title_edited_in_review_still_finds_the_old_entry`
  修之前失败（`applied.error == '没找到要作废 / 修改的条目：…'`），加 4 行后通过。
- **本次新增的另外两条**（钉住既有行为，写出来就是绿的）：
  `test_accepting_change_and_retire_rewrites_every_target_in_place`（先接受两条 add，再来一轮 change + retire：受管块里原位
  改、项目文件与索引行删掉、知识库那篇多「已作废」一节、计数对）；
  `test_retire_of_something_distill_never_wrote_stays_pending_with_a_reason`（作废手写的内容：报错、`CLAUDE.md` 逐字不变、
  提案留在待审）。
- `ruff check pet tests`：All checks passed。
- 蒸馏族 5 个文件：98 passed（2.06 s）；加上 `test_config_schema` / `test_architecture` / `test_pr_report_discipline`：
  260 passed。
- **全量**（本 worktree，PowerShell 启动，`QT_QPA_PLATFORM=offscreen`，`APPDATA` 重定向，`-X faulthandler`）：
  **6 failed / 6080 passed / 14 skipped，10 min 27 s**，无原生崩溃。6 个失败全在既有基线里
  （[`PR-REPORT-ISLAND-COLLAPSE-RETURNS-2026-11-06.md`](PR-REPORT-ISLAND-COLLAPSE-RETURNS-2026-11-06.md) 第六节那 7 个中的 6 个；
  第 7 个只在从 Git Bash 启动时出现）：`image_directory_picker…`、`festival_id_guard_survives_optimize`、
  `real_second_process_refused_on_overlay_topology`、`capture_window_rect_coordinates_and_clamping`、
  `host_icons_are_warmed_at_the_cards_size`、`modern_context_menu_has_compact_semantic_groups`。本分支没有改动这些测试及其
  被测文件（`git diff --stat origin/main HEAD -- pet/context_menus pet/sprite_menu_facade.py tests/test_desktop_pet_features.py` 为空）。

## 七、已知限制与后续

- **模型输出不是合法 JSON 时，尾部的项被静默丢掉**（本次实机 5 项丢 1 项）。抢救逻辑本意是对付「输出到顶被截断」，
  但同一条路也吞掉了「中间有一项引号没转义」的情况，且不标 `truncated`、游标照常推到底——那一项对应的候选不会再送。
  后续：抢救时在状态里写明「丢了几项」，并考虑逐项解析而不是整段解析。
- **个人 / 公司只按 cwd 分**是定案（Windows 路径 = 个人）。本次实机里，在 Windows 路径下开的会话即使聊的是工作相关的
  本机工具，也按规则算个人侧、进了个人 key 的蒸馏。规则本身没问题就不用动；若不想这样，要靠「公司目录」设置把那些目录划过去。
- `backups/` 不清理（每次改 `CLAUDE.md` 一份，本机 1.7 KB / 份）。
- 提案页不能批量操作；`change` 没写 `replaces` 且条目库里找不到同名旧条目时按新增处理（原有行为）。
- **第三期没做**：公司侧在 WSL 里单独抽取、用公司账号蒸馏、写进公司侧知识库。
- 「先全人工审核」仍是现状；要改成自动接受时按约定先提醒本人。

## 八、风险与回滚

- 风险集中在「接受」这一下会写 `~/.claude/CLAUDE.md`：只动受管块、块外逐字不变（测试与实机副本都验证了），改前有整文件备份
  在 `%APPDATA%\big-fat-fish\memory-distill\backups\`。
- 功能默认关（`enabled=False`）：不开就只有每小时一次约 85 µs 的 `check()`，不调模型、不写任何文件。
- 回滚：revert 本 PR 的 squash 提交即可。已写进 `CLAUDE.md` 受管块和项目 memory 的条目是普通文本，不依赖代码存在；
  `%APPDATA%` 下的 `proposals.json` / `entries.json` 留着无害，第一期代码不读它们。
