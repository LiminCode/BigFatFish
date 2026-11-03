# PR 报告：从运行清单认领的会话小鱼，退出后要退场；肥鱼自己的无界面运行不认领（2026-11-02）

> **基线**：`d630e7c9`（Merge PR #13，会话小鱼跨重启）
> **分支**：`claude/fish-adopted-reap`　**日期**：2026-11-02
> **范围**：8 个文件（实现 3、测试 2、文档 3）
> **关联**：[`PR-REPORT-SESSION-FISH-PERSIST-2026-11-02.md`](PR-REPORT-SESSION-FISH-PERSIST-2026-11-02.md)（本文修的是它引入的认领路径的漏洞）、
> 模板 [`PR-REPORT-TEMPLATE.md`](PR-REPORT-TEMPLATE.md)

## 一、核心特性

**实机现象（2026-11-02 23:11）**：岛下面多了一条「SDK / 脚本 · WSL，`/home/<用户>`，工作中」的小鱼，一刻钟后还在。
日志：`23:11:20 从运行清单认领 Claude Code 会话 agent=claude_wsl session=33404817 phase=working`，15 秒后
`Slack 关注完成：用时 17 秒`。它是肥鱼**自己**在 WSL 里起的 Slack 关注（`cd ~ && BIG_FAT_FISH_HEADLESS=1 claude -p …`，
`pet/slack_watch.py`）。进程退出时 Claude Code 删掉了它的清单文件（`~/.claude/sessions/<pid>.json`），但：

- `BIG_FAT_FISH_HEADLESS` 让肥鱼装的 hook 对这次运行一声不吭（`pet/claude_hooks.py` 第 59 行）——没有 SessionEnd；
- `_reap_dead_sessions` 对「清单里没有记录」（liveness = None）的会话按设计**不动**（hook 出场的会话本来就可能没有记录）。

两条规则叠在一起，这条鱼就永远「工作中」。同样的坑适用于任何**认领来的**会话：被 `kill -9`、断电、`claude -p` 脚本——
凡是不走 hook 退场、又会把清单文件删掉的，都收不走。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 清单里见过、又连着两轮没有 = 结束 | `ClaudeSessionTracker.mark_registry / registry_vanished`：认领（`adopt`）、补事实（`note_registry`）、存活核对给出 True / False 都算「见到」；之后 liveness 为 None 时计一次没见到，连着 2 轮（≈2 分钟）按 `SessionEnd` 处理。清单里从没见过的会话维持原规则 |
| 2 | wsl.exe 起不来不是「清单里没有」 | `wsl_liveness` 失败改为抛 `RuntimeError`，调用方本来就按「这一轮核对作废」跳过；不改的话一次 wsl.exe 失败会被当成所有 WSL 会话都没了 |
| 3 | 肥鱼自己的无界面运行不认领 | `WSL_SCRIPT` 对每个活着的清单进程看一眼 `/proc/<pid>/environ`，带 `BIG_FAT_FISH_HEADLESS=` 的输出 `@@headless <pid>`；`parse_wsl_output` 给出 `headless` 集合，`wsl_registry_sessions` 跳过它们。用户自己用 SDK 跑的脚本（`sdk-cli` 但没有这个变量）照认 |

**红线 / 不变量**：
- hook 出场、清单里从没见过的会话：liveness None 仍然不动（既有用例 `test_monitor_retires_sessions_whose_process_is_gone` 原样通过）。
- 进程明确死了（False）的处理不变；认领 / 补事实的更新内容不变（`adopted="1"` 等）。
- 本机（Windows）侧不做无界面过滤：肥鱼在 Windows 侧不起 `claude -p`（个人助理走 API key），没有对应的进程环境可查。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/claude_hooks.py` | +28 / −2 | `ClaudeSessionTracker` 加 `_registry_missed`（清单里见过的会话 → 连着没查到的轮数）、`_REGISTRY_MISSES = 2`、`mark_registry()`、`registry_vanished()`；`adopt` / `note_registry` 都算见到（`note_registry` 现在先记「见到」再判断有没有变化）；`_session_gone` / `reset` 清掉计数 |
| `pet/agent_link.py` | +10 / −0 | `_reap_dead_sessions`：verdict None → 问 `registry_vanished`，到数了按 SessionEnd 收（日志「已从运行清单消失，按已关闭处理」）；True / False → `mark_registry` |
| `pet/claude_session_info.py` | +23 / −4 | `WSL_SCRIPT` 多一段：活着的进程查 `/proc/<pid>/environ` 里有没有 `BIG_FAT_FISH_HEADLESS=`，有则 `@@headless <pid>`；`parse_wsl_output` 解析成 `headless`（按 pid 对回 sessionId）；`wsl_registry_sessions` 认领前剔除；`wsl_liveness` 失败抛 `RuntimeError` 并写明为什么 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_claude_hooks.py` | +20 / −0 | 追踪器：没见过的永远不算；见过的第一轮不算、第二轮算；`mark_registry` / `note_registry` 重新数 |
| `tests/test_session_pet_details.py` | +61 / −1 | `wsl_liveness` 失败抛出（原用例改期望）；脚本含 `BIG_FAT_FISH_HEADLESS` 与 `@@headless`，解析出 `headless`、活着照样标活、`wsl_registry_sessions` 不认领；监视器：认领的会话清单消失 → 第一轮不动、第二轮收走，hook 出场的不动，中途再出现要重新数 |

### 文档

| 文件 | 改动 |
|---|---|
| `docs/PR-REPORT-SESSION-FISH-ADOPTED-REAP-2026-11-02.md` | 新增（本文） |
| `docs/INDEX.md` | +1 行登记；`PR-REPORT-SESSION-FISH-PERSIST` 那行的「何时必读」指到本文 |

### 未改动（故意）

- `pet/slack_watch.py` / `pet/work_briefing.py`：命令行不动，`BIG_FAT_FISH_HEADLESS=1` 本来就在，现在只是多了一个读它的人。
- 不记录「肥鱼自己起了哪些运行」去按 session id 过滤：`claude -p --no-session-persistence` 的 session id 肥鱼拿不到，而进程环境是现成、精确的线索。
- `local_liveness` 不改：本机清单目录读不到时所有会话都 None，有「连着两轮」兜着；本机也没有无界面运行。

## 三、实现要点

**为什么是「连着两轮」而不是一轮**：清单文件由 Claude Code 自己维护，重写的瞬间可能读不到；两轮（存活核对 60 s 一次）把一次
抖动吸收掉，代价是认领来的会话最多晚 2 分钟退场。hook 出场的会话一旦在清单里被看到过（存活核对给过 True / False、或认领路径补过事实），
同样进入这条规则——它本来就应该在清单里。

**为什么 `wsl_liveness` 要抛**：原来失败返回全 None，和「清单里没有」一个样。有了「没有 = 可能结束」的规则后，这两种情况必须分开；
`_reap_dead_sessions` 的 `except Exception: … return` 正好是「这一轮作废」。

**无界面标记放在脚本里而不是 Windows 侧**：进程环境只有发行版里读得到；脚本已经为跳转读过 `/proc/<pid>/environ`
（`TERM_PROGRAM` / `WT_SESSION`），这里是同一个文件再 grep 一个键，只对活着的进程做（死进程 `/proc` 没有，直接跳过）。

## 四、性能分析

**方法（可复现）**：PowerShell 起 `.venv\Scripts\python.exe`，分别把改前（`d630e7c9`）与改后的 `claude_session_info.WSL_SCRIPT` 交给
`claude_hooks.run_wsl` 跑 5 次计时（真机：WSL 2 `Ubuntu-24.04`，清单目录 65 个文件、其中 12 个进程活着）。环境：Windows 11 Pro 26300、
Python 3.13.15。

| 指标 | 实测 | 归属 |
|---|---|---|
| 旧脚本一次（清单 + 存活） | 159 / 145 / 143 / 147 / 148 ms，中位 **147 ms** | 既有 |
| 新脚本一次（多查 12 个活进程的 environ） | 171 / 168 / 159 / 159 / 175 ms，中位 **168 ms** | 既有路径 +21 ms |
| 每分钟调用次数 | 2（存活核对 + 认领，各 60 s 一次，WSL 通道开着时） | 既有，不变 |
| `registry_vanished` / `mark_registry` | 字典查改，微秒级 | 新增 |
| 内存 | 每个在场会话多一个 int（`_registry_missed`，随会话一起删） | 新增，可忽略 |

**结论**：① 稳态：WSL 通道每分钟两次 wsl.exe 调用不变，每次多约 21 ms（+14%），全在后台线程；本机通道零变化。② 新增路径
只是清单脚本里对活进程多一次 `tr | grep`，死进程不查。③ 没有新的子进程、线程、网络、磁盘写入。④ 内存按在场会话数线性增长一个整数。

## 五、实机运行记录

**前提复现**：见 §一的日志摘录（`23:11:20 认领 … 33404817 phase=working` → `23:11:35 Slack 关注完成` → `23:23:40` 用户点那条鱼
「跳到对话」时它还在）。去 WSL 里找它的清单文件已经没有了（进程退出即删），进程表里也没有。

**修复后的真机探针（不花任何模型调用）**：桌宠从本分支的工作区重启（`BigFish.exe -m pet`，日志 `pet-53624.log`），
然后在发行版里用一段脚本种两条**假的**清单记录，各由一个 `sleep 900` 进程撑着：

- A：进程环境带 `BIG_FAT_FISH_HEADLESS=1`，清单写成 `status: busy`、`entrypoint: sdk-cli`、`cwd: $HOME`——和 Slack 关注那次一模一样；
- B：普通进程，`status: idle`、`entrypoint: cli`、`cwd: $HOME/fake-project`。

```
A(headless) pid=1669784 sid=676a632f-…   A env marker lines: 1
B(plain)    pid=1669785 sid=d02b3098-…
```

日志（`pet-53624.log`，时间为本机）：

```
23:36:59  两条假记录写入（桌宠 23:36:33 启动）
23:37:36  从运行清单认领 Claude Code 会话 agent=claude_wsl session=d02b3098 phase=resting   ← B 被认领
23:37:37  会话小鱼出场 agent=claude_wsl session=d02b3098（在场 20 只）
          （A = 676a632f 从头到尾没有一条日志：带无界面标记，认领时被跳过）
23:39:03  B 的 sleep 被 kill、B 的清单文件删掉
23:40:37  Claude Code 会话已从运行清单消失，按已关闭处理 agent=claude_wsl session=d02b3098   ← 两轮存活核对之后
23:40:38  会话小鱼离场 agent=claude_wsl session=d02b3098
23:40:38  冻结的会话小鱼出场 agent=claude_wsl session=d02b3098
```

- B：认领后 37 秒出场，清单文件删掉后 **95 秒**（两轮 60 s 的存活核对）按已关闭收走——修复前这一步永远不会发生。
- A：在清单里待了 4 分多钟（跨 4 个认领周期），日志里一次「认领」都没有。
- 收走后它按 #13 的既有语义变成一条**冻结的**鱼（「最近开过、进程已不在的对话」）：对真实结束的会话这是预期行为；
  肥鱼自己的无界面运行不会走到这一步，因为它们根本不被认领。探针结束后假记录、`sleep` 进程和桌宠历史里的两条假会话都清掉了。

**测试**：`ruff check pet/ tests/` 通过；新用例在没有实现时 4 个全红（`git checkout -- pet/` 后复跑），实现后
`test_claude_hooks` / `test_session_pet_details` / `test_claude_link` / `test_overlay_session_pets` 180 项全绿。全量 `pytest -q`
（隔离工作区，12 分钟）：**5907 通过、5 失败、14 跳过**，5 个都不是本分支的——4 个本机既有基线失败（路径超 260、cp1252 子进程解码 ×2、
多显示器负原点），加 `test_session_card_metro.py::test_host_icons_are_warmed_at_the_cards_size`（在基线 `d630e7c9` 上原样失败）。
