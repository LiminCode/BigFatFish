# 会话记忆蒸馏·第三期（四）：公司侧条目镜像进公司侧知识库副本

> **基线**：main（第三期（三）公司侧落盘合并之后）
> **分支**：`feature/memory-distill-work-mirror`　**日期**：2026-11-10
> **范围**：15 个文件（实现 7、文案 2、测试 4、文档 1 + 索引）
> **关联**：[`PR-REPORT-MEMORY-DISTILL-WORK-SINK-2026-11-10.md`](PR-REPORT-MEMORY-DISTILL-WORK-SINK-2026-11-10.md)、
> [`PR-REPORT-WORK-NOTES-2026-10-15.md`](PR-REPORT-WORK-NOTES-2026-10-15.md)（WSL 里跑 git 的那条通道）

## 一、核心特性

10-30 的定案里公司侧和个人侧一样有第三个落点：知识库镜像。个人侧镜像进个人知识库；公司侧镜像进**公司侧知识库
副本**（工作笔记用的那个仓库克隆，目录取自工作笔记的设置），不进个人知识库。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 接受后写镜像 | 公司侧条目落进 WSL 之后，把公司侧条目库整篇渲染成 `memory/Claude Memory.md`（全局一节、每项目一节、已作废一节） |
| 2 | git 经 WSL 提交推送 | 复用工作笔记的同步通道（`work_notes.sync`），只 `git add` `memory/`；与工作笔记 / Slack 关注共用一把进程级锁 |
| 3 | 可关、看得见 | 设置「公司侧镜像进知识库」（默认开）；接受后的状态行写明镜像去向；推送失败在状态行和「落盘」格上看得到 |

**红线 / 不变量**：公司侧条目不写进个人知识库、不调个人仓库的 git / Token；提交说明只有时间戳，不含条目内容；
WSL 那步没成就不写镜像；没有知识库副本目录不算失败；工作笔记自己的同步命令逐字不变。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/work_notes.py` | +7 / −5 | `sync_command(repo_dir, message, paths=SYNC_PATHS)` / `sync(..., paths=)`：允许别的功能往同一个仓库提交别的目录；默认值不变 |
| `pet/memory_distill_sink.py` | +12 / −6 | `WORK_VAULT_DIR` / `WORK_VAULT_NOTE` / `WORK_VAULT_INTRO`；`render_vault_note(intro=)`、`write_vault_note(note=, intro=)`（默认值 = 个人侧原样） |
| `pet/memory_distill_wsl_sink.py` | +12 / −4 | `apply_proposal(vault_dir=, mirror=)`：WSL 两步都成之后写镜像；失败分支把 `vault_written` 一并清掉 |
| `pet/memory_distill_service.py` | +53 / −1 | `work_vault_dir()`（工作笔记的 `repo_dir`）；`_apply_work` 传镜像参数；`sync_work_vault()`（后台线程、`WORK_GIT_LOCK`、结果经 `_work_sync_done` → `work_sync_state` / `work_sync_error`、发 `synced`）；`stats()["vault_work"]`；先发 `reviewed` 再起推送 |
| `pet/memory_distill.py` | +1 | 配置 `work_mirror_to_vault`（默认开） |
| `pet/memory_distill_ui.py` | +5 / −2 | 接受后的目标文案加镜像；「落盘」格的推送中 / 失败两侧任一即显示 |
| `pet/settings_memory_distill.py` | +7 | 设置行 `distill_work_mirror` |
| `pet/locale/zh.json`、`pet/locale/en.json` | 各 +4 / −1 | 3 条新文案 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_memory_distill_work_mirror.py`（新增） | +186 | 同步命令的 `paths`（默认逐字不变）；落盘时写镜像（两节、写明 WSL、LF）、关掉不写、没有副本不算失败、WSL 失败不写；服务：推送命令只提交 `memory/`、提交说明不含条目内容、个人知识库与个人 git 不碰；推送失败条目仍已接受、页面报出原因；状态行文案；设置开关 |
| `tests/test_memory_distill_work_sink.py`、`tests/test_memory_distill_work.py` | +1 / 0、+3 / −1 | 测试服务显式把工作笔记的仓库目录指到不存在的临时路径——默认值是本机真实的知识库副本，不指开的话测试会往真实目录里写 |
| `tests/test_memory_distill_ui.py` | +1 / −1 | 设置行顺序加 `work_mirror` |

### 未改动

`work_notes_service.py`（只导入它的 `_GIT_LOCK`）。个人侧镜像（`sink.sync_vault` → `personal_vault.sync_path`）不变。

## 三、实现要点

- **为什么 git 在 WSL 里跑**：公司仓库的 SSH 密钥与公司 GitHub 登录只在 WSL；副本放在 NTFS、WSL 经 `/mnt/c` 访问
  （工作笔记当时的定案）。镜像文件本身是本机普通文件写入。
- **只提交 `memory/`**：`git add -A -- 'memory'`。仓库里别人没提交的改动、工作笔记正在写的 `note/` 不会被带进这次提交。
- **提交说明只写时间**：`claude memory: <日期 时间>`——条目标题可能含公司内容，不放进提交历史的标题行。
- **先报「已写入」再推**：推送要几秒；它的结果（尤其失败原因）后到，不会被「已写入」盖掉。
- **取舍**：目录设置复用工作笔记的 `repo_dir`，没有另加一项——两者指的是同一个仓库；镜像文件名与个人侧同名
  （`Claude Memory.md`），目录不同（`memory/`）。

## 四、性能分析

**方法**：`scratchpad/real_mirror_git.py`——真实 `wsl.exe` + 真实 git，仓库是 scratchpad 里临时建的（裸仓库当远端 + 克隆，
在 `/mnt/c` 下），条目是合成的；三种工作区状态各同步一次。环境：Windows 11、Python 3.13、WSL2 Ubuntu 24.04。

| 指标 | 实测 | 归属 |
|---|---|---|
| 写镜像文件（1 条条目） | 498 字节，CR 0 | 新增，每接受一条公司侧提案一次 |
| 同步（add + commit + pull --rebase + push，本地远端） | 1,037 ms / 931 ms | 新增，同上；真实远端另加网络往返 |
| 同步被 git 拒绝时 | 392 ms 返回失败 | — |

**结论**：① 稳态无新增开销。② 新路径只在接受公司侧提案之后走，一秒量级，在后台线程。③ 新增系统调用：每次一个
`wsl.exe`（里面是 4 条 git）；网络由 WSL 里的 git 发；磁盘只有那篇镜像。④ 内存无增长。

## 五、实机运行记录

- **实机输出**（2026-11-10，一次性仓库）：

  ```
  clean tree: ok=True out='' 1037 ms
     remote commits: 2 | files in last remote commit: memory/Claude Memory.md | 14 ++++++++++++++; 1 file changed …
  untracked file elsewhere: ok=True out='' 931 ms
     remote commits: 3 | files in last remote commit: memory/Claude Memory.md | 2 +-; 1 file changed … | local status: 1 ??;
  modified tracked file elsewhere: ok=False out='' 392 ms
     remote commits: 3 | … | local status: 1  M;      1 ??;
  ```

  前两种情况推上去的提交都只含 `memory/Claude Memory.md`，别处没跟踪的文件留在原地。
- **抓到的一个既有限制**：工作区里有**已跟踪文件的未提交修改**时 `git pull --rebase` 拒绝执行，镜像这次提交留在本地、
  没推上去，而且失败输出是空的（见第七节）。真实副本此刻只有 1 个未跟踪文件（`git status --short` 首列 `??`），
  属于能推的那种情况。
- **为什么不在真实的知识库副本上跑**：往公司仓库推送只能发生在用户自己接受一条公司侧提案之后；本任务不替用户接受。
  真实副本在这些运行前后 `git status` 都是同样的 1 行、没有 `memory/` 目录。
- **用户可见行为**：`test_push_failure_keeps_the_note_and_is_reported` / `test_review_status_names_the_work_vault`
  （真实窗口 + 真实服务）。桌宠从含本改动的 main 重启后的记录见下面的追记。

## 六、测试与验证

- **红 → 绿**：`tests/test_memory_distill_work_mirror.py` 先写；实现后有一条（推送失败原因被「已写入」盖掉）仍红，
  调整了发信号与起推送的先后才绿。
- `ruff check pet tests`：All checks passed。蒸馏族 9 个文件 + i18n + 工作笔记族 + 架构：223 passed。
- 全量 pytest：见 PR 描述。

## 七、已知限制与后续

- **同步命令只把最后一条 git 的 stderr 并进输出**（`work_notes._run_git` 在整串 `a && b && c` 后面加 `2>&1`），所以
  `pull --rebase` 被拒时失败原因是空的，页面上只能显示「没有输出」。这是工作笔记通道的既有行为，本 PR 没改
  （改它会同时改变工作笔记的报错文案）；建议后续单独修成 `{ …; } 2>&1`，并考虑 `pull --rebase --autostash`。
- 推送失败后没有自动重推：提交留在本地，下一次接受公司侧提案（或工作笔记的任一次同步）会一并推上去。
- Obsidian 里要先把这个副本登记成库才能直接打开那篇（工作笔记的既有前提）。
