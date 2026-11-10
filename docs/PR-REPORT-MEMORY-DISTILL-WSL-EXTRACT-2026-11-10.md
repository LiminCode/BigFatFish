# 会话记忆蒸馏·第三期（一）：WSL 里的会话也抽进候选库

> **基线**：main（「丢项」修复合并之后）
> **分支**：`feature/memory-distill-wsl-extract`　**日期**：2026-11-10
> **范围**：12 个文件（实现 5、文案 2、测试 3、文档 1 + 索引）
> **关联**：[`PR-REPORT-MEMORY-DISTILL-PHASE1-2026-10-31.md`](PR-REPORT-MEMORY-DISTILL-PHASE1-2026-10-31.md)（抽取与候选库）、
> [`PR-REPORT-MEMORY-DISTILL-PHASE2-LAND-2026-11-10.md`](PR-REPORT-MEMORY-DISTILL-PHASE2-LAND-2026-11-10.md)

## 一、核心特性

抽取此前只扫 Windows 的 `~\.claude\projects`。桌面版开的 WSL 会话存在 Windows 这边的 `projects/ssh-*`，所以扫得到；
但在 WSL 终端 / VS Code Remote 里跑的 Claude Code 把会话记录写在 WSL 自己的 `~/.claude/projects`，一条都没扫——
用户在那边说过的规矩，候选库里 0 命中。本机实测那边有 1420 个项目目录、其中 91 个 transcript 共 331 MB
（其余目录只剩 memory 或已被清理）。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 抽取时一并读 WSL 默认发行版 | 先在 WSL 里一次 `find` 列出 (大小, 路径)，再经 `\\wsl.localhost` 共享只读**长了的**文件 |
| 2 | 一律公司侧 | WSL 来的候选强制 `side=work`，不再看每条记录的 cwd（没写 cwd 的记录不会漏到个人侧） |
| 3 | 不为定时增量叫醒 WSL | 定时那趟先看默认发行版在不在跑（`wsl -l -v`，不会拉起发行版），没在跑就跳过；手动「现在抽取」一定去 |
| 4 | 同一条记录只存一次 | 桌面版开的 WSL 会话两边各有一份（实机 27 条重复）；按记录 id 去重 |
| 5 | 设置里可关、页面看得见 | 新开关「也扫 WSL 里的会话」（默认开）；「会话记录」那格写其中几个来自 WSL；WSL 没问到时状态行写明 |

**红线 / 不变量**：Windows 这半的扫描路径、游标格式、分侧规则不变；WSL 那半失败（没装、没问到、共享读不了）不影响
Windows 这半，也不动 WSL 的游标；公司侧候选仍只入库，这个 PR 不蒸馏它们、不把它们发给任何模型。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/memory_distill_wsl.py`（新增） | +69 | 所有要进 WSL 才能做的事的落脚处。本 PR 两个函数：`default_distro_running`（解析 `wsl -l -v` 带 `*` 那行）、`list_transcripts`（跑 `LIST_COMMAND`，返回 `RemoteListing`；问不到返回 `None`，与「问到了、没有文件」区分） |
| `pet/memory_distill.py` | +84 / −31 | 新 `RemoteListing`（root + (相对路径, 字节数) + side）与游标键前缀 `REMOTE_PREFIX="wsl:"`；`CandidateStore.refresh` 加 `remote=`：大小等于游标的文件不打开，其余走新抽出的 `_scan`（原循环体，逐字搬出）；清理游标时 `wsl:` 键只在「这轮列过清单且清单里没有它」时删，绝不 `exists()`；`_scan` 入库前按 id 去重（有新候选才读一遍库）；`extract` / `_candidate_from` 加 `side=` 覆盖；`stats()` 多 `files_remote`；配置多 `scan_wsl`（默认开） |
| `pet/memory_distill_service.py` | +28 / −9 | `refresh_now(manual=True)`：后台线程里按「开关 → 定时则先看发行版在不在跑 → 列清单」决定 `remote`，结果（`ok` / `asleep` / `failed` / `off`）经 `_done` 信号回 GUI 线程存到 `wsl_scan_state`；`check()` 走 `manual=False`；`stats()["wsl"]` |
| `pet/memory_distill_ui.py` | +14 / −2 | `_source_value`（有 WSL 文件就写「其中 WSL N 个」）；设置摘要多一行；抽取完成的状态行在 WSL 没问到时追加一句 |
| `pet/settings_memory_distill.py` | +7 | 设置行 `distill_scan_wsl`（开关，紧跟「自动抽取」），保存进 `scan_wsl` |
| `pet/locale/zh.json`、`pet/locale/en.json` | 各 +7 / −1 | 6 条新文案 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_memory_distill_wsl.py`（新增） | +263 | `wsl -l -v` 解析；清单解析与失败；WSL 文件抽成公司侧（含没写 cwd 的）、没长的不打开、没列清单时游标保留、清单里没了才清、变短重扫；两处同一条只存一次；服务：手动一定去、定时不叫醒、开关关掉不去、WSL 失败不影响 Windows；设置行往返；真实窗口上的数字与状态行（中 / 英） |
| `tests/test_memory_distill.py` | +1 / −1 | 「文件被重写」用例里重写后的记录换了一个 id（同 id = 同一条，现在不会存两遍） |
| `tests/test_memory_distill_ui.py` | +8 / −2 | 设置行顺序加 `scan_wsl`；「只问一次 `~/.claude` 在哪」的计数不把列清单算进去 |

### 未改动

`memory_distill_run.py`（蒸馏仍只挑个人侧）、`memory_distill_sink.py`。`Place.exists` 不 stat UNC 的约定不变。

## 三、实现要点

- **为什么先列清单再读，而不是把 UNC 目录直接当第二个根**：直接当根实测可行但慢——经共享 `glob` 1420 个目录 0.9 s，
  再逐个打开 91 个文件验开头指纹，无变化的一趟也要 2.6 s；而且发行版没起来时一碰共享就会把它拉起来（或卡住）。
  在 WSL 里 `find` 一次 0.1 s 拿到全部大小，没长的文件根本不打开。
- **游标键用 `wsl:<相对路径>` 而不是 UNC 路径**：清理游标时本机键会 `Path.exists()`；UNC 键这么做就违背了
  「不 stat UNC」。`wsl:` 键只凭清单判断去留。
- **「没长就不打开」放弃了什么**：本机文件每次都验开头 256 字节的指纹来认「被整个重写」；WSL 文件只在大小变了时
  才验。一个文件被重写成**恰好同样大小**时认不出来——transcript 是只追加的，可以接受。
- **强制公司侧**：WSL 里登录的是公司账号，那里的会话按定案就是公司侧；逐条按 cwd 判时，缺 cwd 的记录会落到个人侧
  （之后会被发给个人 key），所以对整份文件按来源定侧。
- **去重的成本**：只有某个文件抽出了新候选时才把候选库读一遍取 id 集合（一次 `refresh` 最多读一次）。
- **备选（没做）**：在 WSL 里跑抽取脚本（要求那边有 python、要把规则代码送过去，两份实现会漂）；
  `tail -c +N` 经 `wsl.exe` 读增量（stdout 要按字节传，`run_wsl` 现在按 UTF-8 文本解码）。

## 四、性能分析

**方法**：`scratchpad/real_extract.py`（把真实候选库复制一份，对副本跑真实 `wsl.exe` + 真实共享，连扫三次计时）；
对照组是把 UNC 目录直接当根（`probe_unc.py`）。环境：Windows 11、Python 3.13、WSL2 Ubuntu 24.04（发行版在跑）、
WSL 侧 91 个 transcript 共 330,990,496 字节。各跑一次。

| 指标 | 实测 | 归属 |
|---|---|---|
| `wsl -l -v`（发行版在不在跑） | 74 ms | 新增，定时那趟每小时一次 |
| WSL 里列清单（`find`，91 个文件） | 132 ms（单测 64–106 ms） | 新增，每趟一次 |
| 首扫（列清单 + 读 331 MB + Windows 这半） | 6.0 s，新增 806 条 | 新增，一次性 |
| 无变化复扫（列清单 + Windows 这半） | 134 ms / 129 ms | 新增热路径（每小时一次） |
| 对照：UNC 目录直接当根，无变化复扫 | 2,555 ms（`glob` 942 ms + 逐个打开） | 没采用的方案 |
| 此前（只扫 Windows）无变化复扫 | 约 11 ms（第一期报告） | 既有 |

**结论**：① 稳态每小时多约 0.2 s（一次 `wsl -l -v` + 一次 `find`），都在后台线程；发行版没在跑时只多那 74 ms。
② 新路径首扫 6 s 一次性；之后只读长了的文件的新字节。③ 新增系统调用：每趟最多两次 `wsl.exe` 子进程 + 对长了的
文件经 9P 共享读；没有网络；磁盘只多写候选日文件与游标（游标文件从 22 项到 113 项）。④ 内存：首扫时最大的单个
transcript（约 10 MB）整段读入，和 Windows 这半一样；去重集合是候选 id（本机 1,226 个短字符串）。

## 五、实机运行记录

- **前提的现场复现**（2026-11-10，本机）：真实候选库 420 条里公司侧 63 条，全部来自 Windows 这边的 `projects/ssh-*`；
  WSL 里 `find ~/.claude/projects -mindepth 2 -maxdepth 2 -name '*.jsonl' | wc -l` = 91，一个都不在游标表里。
- **修后**（对真实候选库的**副本**跑，真实 `wsl.exe`、真实共享）：

  ```
  before: 420 {'personal': 357, 'work': 63} files 22 remote 0
  default distro running: True (74 ms); listing: 91 files, 330990496 bytes (132 ms)
  first refresh (list + scan): added 806 in 6009 ms
  second refresh (list + scan): added 0 in 134 ms
  third refresh (list + scan): added 0 in 129 ms
  after: 1226 {'work': 867, 'personal': 359} files 114 remote 91 {...}
  work entrypoints Counter({'claude-vscode': 794, 'claude-desktop': 49, 'cli': 24})
  ```

  公司侧 63 → 867。WSL 里共抽出 831 条不同的记录，其中 27 条与 Windows 这边已有的重复、没有再存（831 − 27 ≈ 804，
  另 2 条是这段时间 Windows 这半新增的个人侧）。
- **验收用例**：用户在 WSL 的 Claude 里说过的那条写作规范，按关键词在公司侧候选里命中（此前 0 命中）。原文不入报告。
- **没有自动验证的**：「发行版没在跑时定时那趟不去」只在单测里用假 `wsl.exe` 验了——实机上要先 `wsl --shutdown`，
  会打断用户正在 WSL 里跑的会话，没有做。`wsl -l -v` 在发行版停着时那一行写 `Stopped` 是 WSL 的既定输出格式。
- **用户可见行为**：真实窗口上的数字由 `test_page_shows_how_many_files_came_from_wsl_…` 覆盖（真实窗口 + 真实服务，
  `wsl.exe` 是替身）；桌宠从含本改动的 main 重启后的实机记录随第三期最后一个 PR 补。

## 六、测试与验证

- **红 → 绿**：`tests/test_memory_distill_wsl.py` 先写，改实现前导入就失败（`memory_distill_wsl` 不存在）。
- `ruff check pet tests`：All checks passed。蒸馏族 6 个文件：113 passed。
- 设置变更门禁（`docs/SETTINGS-CHANGE-GATES.md`）：`scan_wsl` 是持续偏好、有安全默认（开；没有 WSL 时等于没开）、
  归属唯一（会话记忆蒸馏一节）；旧配置没有这个键时按默认开，无需迁移；三端共用同一 key，非 Windows 上
  `wsl_exe()` 为空、两个问询都直接失败。
- 全量 pytest：见 PR 描述。

## 七、已知限制与后续

- 只扫默认发行版。
- 公司侧候选到这一步仍只入库；蒸馏、审核分侧、公司侧落盘是后面几个 PR。
- 真实库里早先已有 33 条重复 id（文件被重写时整份重扫留下的），本 PR 之后不再新增，旧的没有清理。
