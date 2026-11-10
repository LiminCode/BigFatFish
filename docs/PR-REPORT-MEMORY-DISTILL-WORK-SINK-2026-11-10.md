# 会话记忆蒸馏·第三期（三）：提案页分侧，公司侧提案接受后写进 WSL

> **基线**：main（第三期（二）公司侧蒸馏通道合并之后）
> **分支**：`feature/memory-distill-work-sink`　**日期**：2026-11-10
> **范围**：10 个文件（实现 4、文案 2、测试 2、文档 1 + 索引）
> **关联**：[`PR-REPORT-MEMORY-DISTILL-WORK-CHANNEL-2026-11-10.md`](PR-REPORT-MEMORY-DISTILL-WORK-CHANNEL-2026-11-10.md)、
> [`PR-REPORT-MEMORY-DISTILL-PHASE2-2026-10-31.md`](PR-REPORT-MEMORY-DISTILL-PHASE2-2026-10-31.md)（个人侧落盘）

## 一、核心特性

上一个 PR 之后公司侧能蒸馏出提案，但页面上分不出哪条是公司侧的、没有手动触发的按钮、接受会被拒绝。本 PR 把这三样补上：
公司侧提案经人工接受后，写到 **WSL 里**的 Claude Code 会读的地方——和个人侧同样的两个落点、同样的格式。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 提案页分侧 | 公司侧提案列表行前标「公司」、详情头写「公司侧（写进 WSL）」；「上次总结」两侧各一行 |
| 2 | 「总结公司侧」按钮 | 手动把公司侧候选交给 WSL 里的公司账号；与「现在总结」（个人侧）互不占用 |
| 3 | 全局条目 → WSL 的 `~/.claude/CLAUDE.md` 受管块 | 同样的起止标记；块外逐字不动；改前整份备份到本机 `memory-distill/backups/CLAUDE.md.wsl.<时间>.bak` |
| 4 | 项目条目 → WSL 的项目 memory | `~/.claude/projects/<编码>/memory/distill-<id>.md` + `MEMORY.md` 一行索引；作废时删文件、删索引行 |
| 5 | 公司侧条目库独立 | `entries-work.json`；个人侧的 `entries.json`、CLAUDE.md、项目 memory、个人知识库一概不碰 |

**红线 / 不变量**：仍是逐条人工接受 / 改 / 拒，没有任何自动接受；个人侧提案的落点与行为不变；公司侧提案**不会**写到
个人侧的任何文件，也不触发个人知识库的推送；WSL 那边读不到 / 写不进时不改任何东西、提案留在待审。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/memory_distill_wsl_sink.py`（新增） | +140 | `read_text` / `write_text` / `remove`：经 `wsl.exe` 读写 WSL 里的文件（路径白名单：只许 `$HOME/.claude/` 之下、限定字符、无 `..`；读分清「不存在」与「问不到」；含替代字符的读结果拒收；写 = 同目录临时文件 → 照抄权限 → `mv`）。`apply_proposal`：条目库 → 受管块 / 项目 memory，任何一步失败把条目库退回 |
| `pet/memory_distill_sink.py` | +18 / −8 | `EntriesStore(root, side)`（公司侧 → `entries-work.json`）；`index_text`（原 `_update_index` 里的纯文本那半，两侧共用）；`Applied.side` |
| `pet/memory_distill_service.py` | +52 / −16 | `entries(side)`；`review()` 对公司侧的「接受」改走 `_apply_work`（后台线程，结果经 `_review_done` 回 GUI 线程再记提案状态、发 `reviewed`），正在写的提案不叠加；`stats()["entries_work"]`；蒸馏时「已落盘条目」只带同侧的 |
| `pet/memory_distill_ui.py` | +48 / −13 | `distill_work_btn` + `distill_work_requested`；`proposal_label` / 详情头的侧标；`run_lines`（两侧各一行）；状态行与气泡的「公司侧 · 」前缀；接受后的结果文案分侧；「落盘」那格加公司侧条数；控制器 `distill_now(side)` 按侧判忙 |
| `pet/locale/zh.json`、`pet/locale/en.json` | 各 +12 / −3 | 10 条新文案；`distill.sides.where` 去掉「第二 / 三期」的预告；删掉上一 PR 的占位文案 `distill.work.sink_pending` |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_memory_distill_work_sink.py`（新增） | +324 | 路径白名单；读的三种结果；全局条目进受管块（块外含 CRLF 行逐字不动、备份、同秒不覆盖备份、原位替换）；项目条目与索引、worktree 归主仓库；change / retire；读 / 写失败时不写、条目库回滚；服务：公司侧接受只写 WSL、个人侧的 CLAUDE.md / 项目目录 / 知识库 / git 都没被碰、在后台线程里做且失败留待审、个人侧条目不写 WSL；真实窗口：按钮、侧标、两行「上次总结」、接受后的文案、落盘格 |
| `tests/test_memory_distill_work.py` | −13 | 删掉上一 PR 的占位用例「接受公司侧提案被拒」（被上面的真实落盘用例取代） |

### 未改动

`memory_distill_run.py`、`memory_distill_wsl.py`（只复用 `GLOBAL_CLAUDE_MD` / `project_memory_dir`）。个人侧
`sink.apply_proposal` 一行没动。公司侧知识库镜像（`AI-Base-Memory`）是下一个 PR。

## 三、实现要点

- **为什么经 `wsl.exe` 而不是 `\\wsl.localhost` 共享**：经共享做原子替换会把文件权限重置（`WslSettingsStore` 那里
  实测 600 → 644）；发行版没起来时共享会卡。`wsl.exe` 的标准输入 / 输出实测逐字节保真（LF、中文、无结尾换行）。
- **「块外逐字不动」怎么保证**：读回来的全文原样进 `splice_block`（和个人侧同一个函数），只替换两个标记之间；
  `run_wsl` 解码时把非法字节换成替代字符，所以读结果里一旦有它就拒收，宁可不写。
- **失败回滚**：`EntriesStore.apply` 自己会存盘，所以先记下之前的条目，WSL 那边任一步失败就存回去；不然重试接受会多出
  一条重复条目。已经写成的 WSL 文件不回滚——受管块是从条目库整块渲染的，下次成功时会被重写。
- **为什么放后台线程**：一次接受要 2–3 次 `wsl.exe`（实测共 0.2–0.3 s），发行版冷启动时是几秒；个人侧是本机文件写入，
  仍在 GUI 线程。于是公司侧的 `review()` 立刻返回 `None`，结果从 `reviewed` 信号来（页面本来就听这个信号）。
- **路径白名单**：路径由代码拼（`$HOME/.claude/CLAUDE.md`、`$HOME/.claude/projects/<编码>/memory/…`，编码后只有字母数字
  和 `-`），白名单是第二道防线——提案里的 `project` 来自模型输出。
- **取舍**：备份放本机（`%APPDATA%\big-fat-fish\memory-distill\backups`）而不是 WSL 里——和个人侧的备份、候选库在同一处，
  都是本地不进 git 的数据。

## 四、性能分析

**方法**：`scratchpad/real_wsl_sink.py`——真实 `wsl.exe`，但把 WSL 里的 `HOME` 换成 `/tmp` 下的沙箱目录（里面是真实
`CLAUDE.md` 的副本，5,248 字节），依次接受 4 条**合成**提案并计时。环境：Windows 11、Python 3.13、WSL2 Ubuntu 24.04
（发行版在跑）。各 1 次。

| 指标 | 实测 | 归属 |
|---|---|---|
| 全局新增（读 + 写 CLAUDE.md） | 2 次 `wsl.exe`，191 ms | 新增，每接受一条公司侧全局提案一次 |
| 项目新增（读索引 + 写条目 + 写索引） | 3 次，291 ms | 新增 |
| 全局修改 | 2 次，176 ms | 新增 |
| 项目作废（读索引 + 删 + 写索引） | 3 次，272 ms | 新增 |
| 单次 `wsl.exe` 读 / 写往返 | 约 90 ms | — |

**结论**：① 稳态没有新增开销（`stats()` 多读一个小 JSON）。② 新路径只在用户点「接受」公司侧提案时走，0.2–0.3 s，
在后台线程，不卡界面。③ 新增系统调用：每次接受 2–3 个 `wsl.exe` 子进程；没有网络；本机磁盘多 `entries-work.json`
与每次改 CLAUDE.md 前的一份备份（本机 5 KB 一份，同个人侧一样暂无清理）。④ 内存无增长。

## 五、实机运行记录

- **实机输出**（2026-11-10，沙箱 `HOME`，合成提案）：

  ```
  seed: 640 5248 bytes
  global add: error='' claude_md=True project_file=no removed=False | 2 wsl calls, 191 ms total
  project add: error='' claude_md=False project_file=yes removed=False | 3 wsl calls, 291 ms total
  global change: error='' claude_md=True project_file=no removed=False | 2 wsl calls, 176 ms total
  project retire: error='' claude_md=False project_file=yes removed=True | 3 wsl calls, 272 ms total
  entries: [('global', False), ('project', True)]
  outside the block identical to the real file: yes
  mode kept: 640 | block markers: 2 | bullets in block: 1 | CR in block: 0
  project dir after retire: MEMORY.md 1
  leftover tmp files: 0
  real CLAUDE.md untouched: 0 markers, 5248 bytes mtime 2026-09-27 16:10:29
  ```

  「块外与真实文件逐字节相同」用 `cmp -n <原文件字节数>` 比的；权限 640 保留；没有遗留临时文件。
- **这次跑还抓到一个问题**：4 条提案用了同一个时间戳，第二次改动的备份把第一次的（真正的原件）盖掉了——已修
  （同名备份已存在就不再写），并加了断言。
- **为什么用沙箱而不是真实的 WSL `~/.claude`**：真实文件只能由用户自己审核接受后写入；本任务不替用户接受任何提案。
  真实 `CLAUDE.md` 在这次运行前后都是 5,248 字节、无受管块标记。
- **用户可见行为**：真实窗口的按钮 / 侧标 / 文案由 `test_page_tells_the_sides_apart_and_has_a_work_side_button` 覆盖
  （真实 `MemoryDistillWindow` + 真实服务，`wsl.exe` 与模型是替身）。没有截屏：窗口要等桌宠从含本改动的 main 重启后
  才是新样子，重启记录与真实提案页上的公司侧提案计数随第三期最后一个 PR 补。

## 六、测试与验证

- **红 → 绿**：`tests/test_memory_distill_work_sink.py` 先写，改实现前导入就失败；「同秒备份不被覆盖」那条断言在修之前
  实测失败。
- `ruff check pet tests`：All checks passed。蒸馏族 8 个文件 + i18n + 架构：158 passed。
- 全量 pytest：见 PR 描述。

## 七、已知限制与后续

- 只写默认发行版。
- 个人侧的备份也有「同一秒两次改动互相覆盖」的问题（`sink.write_claude_md`），个人侧落盘在 GUI 线程里人手点不出同一秒
  两次，本 PR 没动它。
- `backups/` 仍无清理；提案页仍无批量操作。
- 公司侧知识库镜像：下一个 PR。
