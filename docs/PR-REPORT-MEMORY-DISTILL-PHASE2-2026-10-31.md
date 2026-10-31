# PR 报告：会话记忆蒸馏·第二期——每日蒸馏、逐条审核、落盘到 CLAUDE.md / 项目 memory / 知识库

> **基线**：`6fc80df2`（第一期合并点之后）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-31
> **提交**：`f69e361d`、`fe2e0ecb`、`de9c017d`、`<报告>`
> **范围**：实现 8 个文件（含文案 2 个）+ 测试 3 个（新）/ 2 个（改）
> **过程**：用户 2026-10-31 说「现在就开始吧」；一次真跑暴露了输出截断，修后再跑；用户审核见「实机运行记录」

## 一、核心特性

第一期把我在 Claude Code 里说过的话抽进了本地候选库。第二期把后三格做实：

```
候选库 ──► 蒸馏（每日 daily_at + 手动「现在总结」，个人 key 的模型）──► 提案 ──► 逐条 接受 / 改 / 拒 ──► 落盘
                                                                                                  ├─ ~/.claude/CLAUDE.md 受管块（全局）
                                                                                                  ├─ ~/.claude/projects/<编码>/memory/（项目）
                                                                                                  └─ AI-Base/User/Claude Memory.md（镜像，push）
```

| # | 内容 | 现在 |
|---|---|---|
| 1 | 送什么给模型 | 上次蒸馏之后、**个人侧**的候选（公司侧一条都不送，第三期在 WSL 里用公司账号），按时间排；超过 150 条先丢「任务」、再丢最老的 |
| 2 | 现有记忆 | 全局 `~/.claude/CLAUDE.md` 全文（含受管块）、已落盘的蒸馏条目清单、本次候选涉及的每个项目的 `memory/MEMORY.md` 索引（各有上限）；worktree 的会话归主仓库 |
| 3 | 「别再提」 | 拒掉的提案标题回灌进提示词，模型下次不再提同样的 |
| 4 | 提示词 | 设置里那份明文（第一期就摆出来了），三个占位符 `{candidates}` / `{memory}` / `{dismissed}`，`render_template` 填 |
| 5 | 提案 | JSON 数组：`add / change / retire`、`global / project`、`user / feedback / project`、一句话、为什么、怎么用、**原话证据**、替换哪条。不合法的项丢掉，模型写的项目名对回候选里的完整路径 |
| 6 | 审核 | 流程页新「提案」页：左边待审列表，右边**可改**的一句话 / 为什么 / 怎么用 + 原话依据；接受 / 拒绝（进别再提）/ 跳过（下次还在） |
| 7 | 落盘 | 接受即写：条目库 `entries.json` 是唯一真相 → 全局条目渲染成 CLAUDE.md 的**受管块**（起止注释，块外一个字不动，改前整文件备份）；项目条目写 `distill-<id>.md`（和我手写的记忆同一种 frontmatter）+ `MEMORY.md` 索引行；`change` 原位改、`retire` 删文件去索引 |
| 8 | 镜像 | AI-Base 的 `User/Claude Memory.md` 整篇由条目库重新生成，`add → commit → pull --rebase → push`（和灵感记录同一条路、同一个 Token）；推送在线程里，失败只提示、文件留着下次再推。设置里可关 |
| 9 | 定时 | `daily_at`（默认 21:30）到点自动跑，今天跑过不再跑，失败歇 20 分钟、一天最多 3 次；定时跑出提案就弹气泡「整理出 N 条待审」 |
| 10 | 流程图 | 后三格不再写「第二期」：上次总结时间与提案数 / 待审·已接受·已拒 / 全局·项目条数与镜像状态；点「审核」格切到提案页，点「蒸馏」格就总结 |

## 二、修改文件说明

> 行数来自 `git diff --numstat 6fc80df2..HEAD`（见文末「数字」）。

### 实现

| 文件 | 改了什么 | 为什么 |
|---|---|---|
| `pet/memory_distill_run.py`（新） | `is_due` / 状态文件；`select_candidates`（个人侧、上次之后、预算）；`format_candidates`；`repo_root` / `encode_project_dir` / `project_dir`（Claude Code 的目录编码 + worktree 归主仓库 + 大小写不敏感匹配）；`memory_context`；`Proposal` / `parse_proposals`（含截断抢救）；`ProposalStore`；`build_prompt`；`run_once` | 蒸馏这一步全是纯逻辑，模型调用注入，测试不花钱 |
| `pet/memory_distill_sink.py`（新） | `Entry` / `EntriesStore.apply`（add / change / retire）；`render_block` / `splice_block` / `write_claude_md`（受管块 + 备份）；`write_project_entry` / `remove_project_entry`（文件 + 索引行）；`render_vault_note` / `write_vault_note` / `sync_vault`；`apply_proposal` | 三个落点一处收口；条目库做唯一真相才能真的改掉 / 作废旧内容 |
| `pet/memory_distill_service.py` | `distill_now`（线程）、`check` 里的 `is_due`、`review`（接受即落盘、推送另起线程）、`sync_vault`、`stats` 多 `distill / proposals / entries / vault` 四块；可注入 `complete / provider / home / token / git` | Qt 侧只管线程与信号 |
| `pet/memory_distill_ui.py` | 「提案」页、后三格数字、`run_line`、`proposal_label`、「现在总结」可点、控制器的 `distill_now / review / _on_distilled / _on_reviewed / _on_synced`、截断说明 | 审核要能改字，不能只是按钮 |
| `pet/memory_distill.py` | 默认提示词加 `{dismissed}` 段；配置多 `mirror_to_vault`（默认开） | |
| `pet/settings_memory_distill.py` | 「镜像进知识库」开关一行 | |
| `pet/personal_vault.py` | `sync_inspiration` 的 add → commit → pull → push 抽成 `sync_path(repo_dir, rel_path, message)`，灵感记录改为调它 | 镜像复用同一条推送路，不复制 |
| `pet/work_briefing.py` | `render_template` 的占位符白名单加 `candidates / memory / dismissed` | 它只换认识的名字（用户模板里的 JSON 花括号不能炸） |
| `pet/locale/zh.json`、`en.json` | `distill.*` 新增 46 键，删 1 键（`distill_phase2`） | |

### 测试

| 文件 | 覆盖 |
|---|---|
| `tests/test_memory_distill_run.py`（新） | 定时三条规则、状态往返、挑候选（侧 / 时间 / 预算先丢任务）、候选格式、目录编码与 worktree 归并、现有记忆上限、提案解析（非法项 / 重复 / 项目名对回 / 没写项目当全局）、**截断抢救**、提案库（合并 / 状态 / 别再提）、`run_once`（提示词内容、模型与强度、`max_tokens`、状态推进、没新候选不调模型、失败与坏输出不推游标）、模板占位符 |
| `tests/test_memory_distill_sink.py`（新） | 条目库 add / change / retire（change 保 id、找不到当 add）、受管块原位替换与块外不动、备份、没变不写、作废后块里消失；项目文件与索引行（重写不重复、删除）；知识库那篇（全局 / 项目 / 已作废）与推送命令序列、灵感记录仍走同一条路；`apply_proposal` 三个落点、worktree 归主仓库、找不到旧条目报错、不镜像 |
| `tests/test_memory_distill_phase2_ui.py`（新） | 服务：蒸馏送个人侧候选并入库、第二次没新候选不调模型、失败报告与重试、定时到点只跑一次 / 关着不跑、接受写三处并推送、拒进别再提 / 跳过不进、推送失败留文件、没有服务商软失败；页面：提案页列表 / 编辑 / 接受 / 拒绝与格子数字、定时跑弹气泡、点审核格切页；设置镜像开关往返 |
| `tests/test_memory_distill_ui.py`、`tests/test_memory_distill.py` | 四页、后三格文案、设置行多一行 |

### 未改动

- 候选库、抽取、分流（第一期）没动；公司侧候选第二期一条都不读。
- 不改 `~/.claude/CLAUDE.md` 受管块以外的任何字；不动项目 memory 目录里非 `distill-` 开头的文件。
- 个人助理、工作笔记逻辑没动（只抽了一个共用函数）。

## 三、实现要点

1. **条目库是唯一真相。** CLAUDE.md 的受管块和知识库那篇都是从 `entries.json` 整体渲染的，所以 `change` / `retire` 是真的改掉旧内容，不是往后追加；项目 memory 文件按条目 id 命名，重写同名文件、索引行按文件名替换。
2. **受管块只动块内。** `splice_block` 找到起止标记原位替换，找不到就追加到文件末尾；改之前把整个 CLAUDE.md 备份到 `memory-distill/backups/CLAUDE.md.<时间>.bak`；内容没变不写。
3. **Claude Code 的目录编码。** `~/.claude/projects/<编码>`：所有非字母数字换成 `-`；worktree（`<仓库>\.claude\worktrees\<名>`）归主仓库——Claude Code 的 memory 目录也是这么归的（本会话在 worktree 里，记忆却在主仓库那个目录）；本机同一仓库出现过 `C--` 和 `c--` 两个目录，所以按大小写不敏感匹配已有目录。
4. **输出截断的抢救**（实机第一次真跑暴露）：high 强度下 16000 个输出 token 几乎全花在思考上，正文 3.6k 字符在第 6 项中间断掉。现在 `max_tokens=32000`、超时 300 s；JSON 没闭合就从后往前找最后一个完整对象补 `]`（那次的输出抢救出 5 条）；`stop_reason=max_tokens` 时结果标 `truncated`，状态行说明「下次会补上」，**游标只推到这批的一半**：后一半下次重送（提案按 id 去重，重送无害），既不丢也不会死循环。
5. **信号顺序。** `changed`（页面重摆数字、清状态行）先于 `distilled` / `refreshed`（写结果），否则结果行被重摆盖掉；手动触发先写「正在总结」再起线程，因为测试里线程是同步替身。
6. **接受在 GUI 线程写文件，推送另起线程。** 文件写入实测 p50 14 ms；git 推送几秒，不能卡界面。
7. **提案没落成就还留在待审。** `apply_proposal` 报错（比如 retire 找不到旧条目）时状态回到 pending，用户看得到原因。

## 四、性能分析

> 环境：Windows 11，`.venv` Python 3.13；真实 transcript（30 个文件 112 MB → 310 条候选，个人侧 247 条）；模型走个人 key。

| 路径 | 实测 | 说明 |
|---|---|---|
| 一次蒸馏（真模型，150 条候选 = 第一次的预算上限） | 输入 **38,972** token、输出 **20,773**（high 强度，大半是思考）、**239.8 s**；第一次（截断）195.6 s | 每天一次 + 手动；后台线程。之后每天几十条，会短得多 |
| `memory_context`（真 home） | **0.6 ms** | 读 CLAUDE.md + 一个 MEMORY.md |
| `apply_proposal`（三个落点都写） | 30 次：**p50 14.1 ms，最大 17.2 ms** | 在 GUI 线程；一次接受一条 |
| `ProposalStore.counts` / `stats()` 新增部分 | **0.1 ms** / 读两个小 JSON | 每次刷新页面 |
| 知识库推送 | 一次 `git add / diff / commit / pull --rebase / push` | 在线程里；和灵感记录同一条路（实测几秒，取决于网络） |
| 定时检查 | 复用第一期每分钟的 `QTimer`：多读一个 state JSON | 可忽略级别的 `is_due` 计算 |

逐条回答：

- **稳态开销**：没新增定时器；每小时的 `check` 多一次 `is_due`（读一个小 JSON）。
- **新增路径成本与触发频率**：蒸馏 = 一次模型调用 / 天（手动另算），输入几万 token（候选 + 现有记忆），输出几千；接受 = 十几毫秒文件写入 + 一次 git 推送。
- **新的系统调用 / 网络 / 磁盘 / 线程**：网络 = 模型 API（个人 key）+ git 推送 GitHub；磁盘 = 候选库目录下 `distill-state.json` / `proposals.json` / `entries.json` / `backups/`、CLAUDE.md、项目 memory 文件、知识库那篇；线程 = 蒸馏一个、推送一个，结束即退。
- **内存**：蒸馏线程里持有候选行列表与提示词字符串（几十 KB～几百 KB），结束释放。

## 五、实机运行记录

**2026-10-31，本机真实环境，真实 transcript，真实个人 key（候选库 / 提案库写在 scratchpad，不碰真实数据目录；没有审核就没有落盘）。**

1. **第一次真跑**：150 条候选（预算上限；全历史第一次），`claude-sonnet-5`、effort high，输入 38,972 token、输出 16,000（到顶）、195.6 s。
   正文只有 3,673 字符、6 项写到第 6 项中间 → 整次按「没按约定输出 JSON」失败。前 5 项看过：都是真规则（跨项目默认中文解释、
   画图原则、一个硬件项目的连接器规格、UI 数值要可配置、一台设备的行号约定），证据都引了原话。→ 放大 `max_tokens`、加截断抢救。
2. **第二次真跑**（修后，同一批 150 条候选）：`claude-sonnet-5`、high，输入 38,972、输出 20,773 token（没到顶），**239.8 s**，
   **5 条提案全部解析入库**：2 条全局 `add`（user 类：跨项目默认中文解释、画图原则），3 条项目 `change`（一个硬件项目的两个
   克隆路径各一条、BigFatFish 一条——它准确地把当天「个人 / 公司判定要讲清、模型要可选」那两句归成对已有记忆条目的修改，
   并写了 `replaces`）。每条都带 1–3 条原话依据，没有编造的。
3. **页面**（`QT_QPA_PLATFORM=windows`，用这次真跑的提案库建页）：「提案 5」页头显示上次总结那行（时间 / 模型 / 强度 /
   token / 秒 / 候选 → 提案）；列表每行「新增 · 全局 · …」「修改 · <项目名> · …」；点开一条，一句话 / 为什么 / 怎么用三个框可改，
   下面是原话依据，右下接受 / 拒绝 / 跳过。流程图第四格写「上次 10-31 01:14 · 5 条提案」，第五格「待审 5 · 已接受 0 · 已拒 0」。
4. **桌宠重启**：`2026-10-31 01:18:14 acquired pid=22140`，主检出快进到 `2dfd517b`；新进程日志无接线错误。把第二次真跑的
   `proposals.json` / `distill-state.json` 复制进真实候选库目录（原来没有这两个文件），用户不用再等 4 分钟就能在实机上审。
5. **用户审核**：待填。

> 报告里不引用提案正文与候选原话（含用户项目名）；只给计数与类别。

## 六、测试与验证

- 新用例在实现之前都是红的（纯逻辑两份测试先写；截断抢救用例对着第一次真跑的输出写、改前红）。
- 聚焦：`test_memory_distill_run.py` 17、`test_memory_distill_sink.py` 5、`test_memory_distill_phase2_ui.py` 10，加第一期两份、i18n、配置 schema、菜单对齐、设置布局、个人助理、简报——全过；`ruff check pet tests` 干净；`git diff --check` 干净。
- 全量：待填。

## 七、已知限制与后续

- **第一次全历史**最多送 150 条，可能要跑两三次「现在总结」才把积压消化完（截断时后一半自动留到下次）；之后每天几十条一次就完。
- **第三期**（公司侧）：WSL 里独立抽取、公司账号 `claude -p` 蒸馏、落 AI-Base-Memory；流程页分两条泳道。
- `change` 按标题找旧条目（同作用域、同项目）；模型把标题改了又没填 `replaces` 时会当 `add`，用户在提案页能看出来（没有「替换」字样）。
- 知识库推送用个人助理那套 Token；Token 被拒时退到 Git Credential Manager（可能弹登录窗）。

## 八、风险与回滚

- 写 `~/.claude/CLAUDE.md` 只在用户点「接受」之后；每次改之前整文件备份；块外不动。回滚 = 删掉受管块（或拿备份覆盖）。
- 项目 memory 只动 `distill-*.md` 与 `MEMORY.md` 里对应的索引行。
- 知识库那篇是新文件 `User/Claude Memory.md`，不碰库里已有内容；不想要就关「镜像进知识库」并删那个文件。
- 代码回滚 = revert 本 PR 的提交；候选库目录下的 `proposals.json` / `entries.json` / `backups/` 可直接删。

## 数字

`git diff --numstat 6fc80df2..2dfd517b`（16 个文件，+2201 / −26；含本报告与索引）：

| 文件 | + / − |
|---|---|
| `pet/memory_distill_run.py`（新） | 456 / 0 |
| `pet/memory_distill_sink.py`（新） | 354 / 0 |
| `pet/memory_distill_ui.py` | 247 / 9 |
| `pet/memory_distill_service.py` | 189 / 3 |
| `pet/memory_distill.py` | 8 / 1 |
| `pet/settings_memory_distill.py` | 6 / 0 |
| `pet/personal_vault.py` | 9 / 3 |
| `pet/work_briefing.py` | 1 / 1 |
| `pet/locale/zh.json`、`en.json` | 47 / 2 ×2 |
| `tests/test_memory_distill_phase2_ui.py`（新） | 295 / 0 |
| `tests/test_memory_distill_run.py`（新） | 251 / 0 |
| `tests/test_memory_distill_sink.py`（新） | 152 / 0 |
| `tests/test_memory_distill_ui.py` | 6 / 5 |
| `docs/PR-REPORT-MEMORY-DISTILL-PHASE2-2026-10-31.md`（新）、`docs/INDEX.md` | 132 / 0、1 / 0 |
