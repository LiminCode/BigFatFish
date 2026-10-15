# PR 报告：「跳到对话」在多文件夹工作区里不再新开一个 VS Code 窗口

> **基线**：`a44eacd`（feat(work-briefing): 简报里的工单 / PR 点得开；灵动岛上加一个打开简报的按钮）
> **分支**：`feature/claude-session-fish`　**日期**：`2026-10-12`
> **范围**：6 个文件（实现 2、测试 2、文档 2 含本报告）

## 一、核心特性

用户反馈：点会话小鱼详情卡上的「跳到对话」，VS Code 新开了一个窗口（只开着那个会话
所在的文件夹），而承载这个对话的窗口明明就在主屏幕上。

**根因**（在用户的真实桌面上确认，见 §五）：承载这个会话的 VS Code 窗口开的是一个
**多文件夹工作区**。它的标题是 `<工作区名> (Workspace) [WSL: 发行版] - <当前标签页>`，
里面没有会话所在的那个文件夹的名字。原来的逻辑只会「在窗口标题里找文件夹名」，找不到
就退到「用 `code` 命令打开这个文件夹」——而没有哪个窗口单独开着这个文件夹，VS Code 就
新开了一个。

改法是不再只靠标题猜，先去问 VS Code 自己：

| # | 线索 | 来源 | 解决什么 |
|---|---|---|---|
| 1 | 会话是哪个窗口的标签页 | 每个窗口自己的状态库 `workspaceStorage/<id>/state.vscdb`，里面记着打开的标签页，Claude 会话的标签页带着会话 ID | 最准。两个工作区都包含同一个文件夹、会话中途 cd 到了工作区外面，都分得清 |
| 2 | 会话的目录属于哪个窗口 | `globalStorage/storage.json` 记着每个窗口开的文件夹 / 工作区文件；工作区文件里写着它包含哪些文件夹 | 多文件夹工作区；同名文件夹开在不同父目录下 |
| 3 | 哪个窗口的当前标签页是这个对话 | 窗口标题里那一段（可能被截断成「前缀…」） | 状态库还没落盘、VS Code 的记录读不到时 |
| 4 | 会话进程启动时所在的目录 | Claude Code 的运行清单（插件把进程起在工作区的第一个文件夹里） | 几个候选窗口里再筛一遍 |
| 5 | 让 `code` 命令去聚焦 | 传给它的是**确切的**文件夹或工作区文件 | 标题分不清（同名窗口好几个、标题被自定义）时。VS Code 按这个目标去重，已经开着的不会新开 |

用户看到的变化：点「跳到对话」，正确的那个窗口被调到前台并切到这个对话，不再冒出新
窗口。「最近的对话」里点一行打开项目时同理——项目是某个开着的工作区的一员，就聚焦那个
工作区。

**红线 / 不变量**

- **活着的会话不新开窗口**。VS Code 的记录读得到、却没有哪个窗口包含这个目录时，说
  「没认出这个对话在哪个 VS Code 窗口里」，不去跑 `code` 命令
  （`test_a_live_session_never_makes_a_new_window_when_vscode_has_no_window_for_it`）。
- **链接只发给调对了的窗口**——既有的这条没有变
  （`test_vscode_jump_never_sends_the_link_to_the_wrong_window` 仍通过）。
- VS Code 的记录完全读不到时，行为与原来一致：按文件夹名找标题，找不到就 `code <文件夹>`
  （`test_without_any_clue_the_old_fallback_still_opens_the_folder`，以及
  `tests/test_session_pet_details.py` 里原有的 5 条跳转用例全部通过）。
- WSL 项目与 Windows 项目不互相冒充
  （`test_windows_and_wsl_projects_do_not_stand_in_for_each_other`）。
- 只读：VS Code 的两处记录都只读不写；状态库以只读方式打开。

## 二、修改文件说明

增删取自 `git diff a44eacd --numstat`。

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/claude_session_jump.py` | +424 / −38 | 新增数据类 `OpenWorkspace`（一个窗口开着的东西：名字、包含的文件夹、交给 `code` 的目标、状态库目录）。读记录：`opened_workspaces` → `workspaces_from_state`（解析 `storage.json` 的窗口清单）、`_workspace_roots`（读工作区文件里的文件夹，相对路径相对工作区文件）、`_strip_jsonc`（工作区文件允许注释和行尾逗号）、`_split_uri`、`_storage_index`（窗口 ↔ 状态库目录）。判断归属：`session_windows` / `_state_mentions`（查状态库）、`owning_workspaces` / `owning_workspace`（按路径）、`narrow_by_start`（按启动目录）、`_shows_session`（按标签页标题）。找窗口：原 `find_vscode_window` 的循环拆成 `_named` + `vscode_candidates`，后者认得 `<名字> (Workspace)`（括号里的词随界面语言变，只认「名字 + 一对括号」）。`_jump_vscode` 按上表的顺序用这些线索。`open_in_vscode` 拆出纯函数 `vscode_command`，多一个 `target` 参数；没给时用 `vscode_target` 查一次归属。`find_wsl_terminal_window` 多一个可选的 `owner` |
| `pet/claude_session_info.py` | +3 / −0 | `apply_registry` 把运行清单里的目录另存一份到 `detail.extra["start_cwd"]`。原来只在 `detail.cwd` 为空时才用它，会话 cd 走之后启动目录就丢了 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_session_jump_workspaces.py`（新增） | +375 / −0 | 26 条。读 VS Code 的窗口清单 4；按路径判断归属 3；按工作区名找窗口 1；跳转 8（多文件夹工作区、同名窗口靠标签页分、分不清交给 `code` 并给确切目标、标题被自定义、活着的会话不新开、没有记录时靠标签页、完全没线索走老路、短标题不误认）；两处并列的情况 2；状态库 4（真的 sqlite 文件）；启动目录 1；WSL 终端 1；`code` 命令 2 |
| `tests/test_session_pet_details.py` | +2 / −1 | 假桌面多注入一个空的窗口记录（否则会去读本机真实的 VS Code 数据）；`vscode` 替身多收一个 `target` 参数 |

### 文档

| 文件 | 改动 |
|---|---|
| `docs/PR-REPORT-SESSION-JUMP-WORKSPACE-2026-10-12.md` | 本报告 |
| `docs/INDEX.md` | 登记本报告 |

### 未改动

- `pet/session_pet_ui.py`、`pet/session_history_service.py`：调用方式没变。前者仍是
  `jump(detail, wsl_env=…)`；后者仍是 `open_in_vscode(detail)`，归属由函数自己查。
- 本机（非 WSL）终端会话的 `find_host_window`：它顺着进程链找窗口，不靠工作区名。
- 聚焦窗口与发链接的那两段（`focus_window`、`open_uri`）。

## 三、实现要点

**为什么不只修「认得工作区名」这一点。** 实机上同一个文件夹被**两个**多文件夹工作区
包含，而且这两个工作区的第一个文件夹还相同。只按路径会得到两个候选，按启动目录也筛
不掉。能分清的只有两条：这个对话是不是某个窗口的当前标签页（看标题），或者 VS Code
自己记着它是哪个窗口的标签页（查状态库）。前者要求对话正好在前台，所以后者是首选。

**状态库是什么。** VS Code 给每个打开过的文件夹 / 工作区建一个目录
`%APPDATA%\Code\User\workspaceStorage\<id>\`，里面的 `workspace.json` 写着它对应的地址，
`state.vscdb` 是一个 sqlite 库。库里 `memento/workbench.parts.editor` 这一项是编辑器区
的标签页状态，`Anthropic.claude-code` 是插件自己的状态；实测前者包含打开着的 Claude
会话的 ID。「是开着的标签页」记 2 分，「只在插件状态里出现」记 1 分，取最高分的窗口；
正好一个才采信。

**它不是实时的。** VS Code 隔一阵才把状态落盘，刚开的会话可能还查不到。查不到就退回
路径 + 标题那一套，所以这条线索只会让结果更准，不会让原来能跳的变成不能跳。

**为什么分不清时交给 `code` 命令而不是取最靠前的窗口。** 三个标题一模一样的窗口（同名
项目在三个父目录下各开一份），取最靠前的那个有三分之二的可能是错的，而错了之后链接会
在错的窗口里新开一个空对话。`code --remote wsl+<发行版> <确切的文件夹>` 由 VS Code
自己按文件夹去重，聚焦的一定是对的那个。代价是慢一些（要等它起来，见 §四）。只有在
连归属都不知道时才取最靠前的。

**发行版名的大小写。** VS Code 的记录里同一个发行版有时写成全小写。读工作区文件走
`\\wsl.localhost\<发行版>\…`，Windows 路径不分大小写，两种写法都读得到；交给 `code`
命令的发行版名用的是会话自己的（大小写正确的）那个。

**没有采用的做法**

- 顺着 WSL 里的进程树找到会话所属的扩展宿主进程，再对应到窗口：每次跳转要多起一次
  `wsl.exe`，而且扩展宿主到窗口的对应关系 VS Code 没有公开。
- 用窗口的位置和大小去对 `storage.json` 里记的窗口位置：最大化的窗口在同一块屏上位置
  都一样。
- 新开窗口之后再把它关掉：治标，而且会闪一下。

## 四、性能分析

**方法**：一次性脚本（会话内，未入库），在用户的真实机器上对真实的 VS Code 数据计时：
8 个窗口，其中 2 个多文件夹工作区（工作区文件在 WSL 里），`workspaceStorage` 下 61 个
目录。环境：Windows 11 10.0.26300，Python 3.13.15，WSL 2。跳转本来就在后台线程里。

| 指标 | 实测 | 归属 |
|---|---|---|
| `opened_workspaces()`（读窗口清单 + 2 个工作区文件 + 建状态库目录索引） | 中位 13.0 ms，p95 15.7 ms，最大 18.1 ms（n=30） | 每次跳转 1 次（新增） |
| 其中：经 `\\wsl.localhost` 读 2 个工作区文件 | 中位 6.9 ms，p95 8.5 ms（n=30） | 同上 |
| 其中：状态库目录索引（61 个 `workspace.json`） | 中位 4.1 ms，p95 5.1 ms（n=30） | 同上 |
| `session_windows()`（8 个窗口各查一次 sqlite） | 中位 1.6 ms，p95 1.9 ms，最大 2.6 ms（n=30） | 每次跳转 1 次（新增） |
| 按路径判断归属 + 按标题找窗口 | 中位 33 µs（n=2000） | 每次跳转 1 次 |
| `list_windows()` | 中位 0.9 ms（n=30） | 既有 |
| 一次真实跳转（聚焦窗口路径） | 0.41 s（n=1），其中 0.35 s 是既有的「等窗口到前台再发链接」 | 用户点一次 |
| 走 `code` 命令的路径 | 没有实测；既有的等待是 1.2 s + 0.35 s | 标题分不清时 |
| 新测试文件 | 26 条 0.6 s | — |

**结论**

1. **稳态开销**：没有。全部发生在用户点「跳到对话」或「最近的对话」里打开项目时。
2. **新增路径**：每次跳转多约 15 ms（中位 13.0 + 1.6），在后台线程里。
3. **新的系统调用 / 网络 / 磁盘 / 线程**：没有网络、没有新线程、没有新进程。多读的
   文件：1 个 `storage.json`、N 个 `workspace.json`（本机 61）、每个多文件夹工作区 1 个
   工作区文件（WSL 里的经 `\\wsl.localhost`）、每个窗口 1 次只读的 sqlite 查询。全部
   只读。WSL 没开着时读 `\\wsl.localhost` 会把发行版拉起来——但会话活着就说明它开着。
4. **内存**：没有常驻的新对象，每次跳转现读现用。
5. **走 `code` 命令的那条路径没有量**：这次实机上没有走到它（状态库直接认出了窗口）。

## 五、实机运行记录

全部在用户的真实桌面上：真实的 VS Code 窗口、真实的会话。项目名、工作区名、对话标题
属于用户的工作信息，这里只记结构，不记名字。

**根因的现场**（修复前，用产品代码列出真实窗口并演算）

```text
VS Code 窗口 8 个。承载这个会话的那个：标题第一段是「<工作区名> (Workspace) [WSL: …]」，
第二段是这个对话标题的前 24 个字符加「…」
按会话的文件夹名在所有标题里找：None
→ 退到 code 命令打开这个文件夹 → VS Code 新开一个窗口
```

**VS Code 自己记了什么**

```text
storage.json：openedWindows 8 条——6 条是文件夹，2 条是工作区文件（configURIPath 指向
              WSL 里的 .code-workspace），文件几十秒前刚被 VS Code 写过
工作区文件：  经 \\wsl.localhost 读到，4–11 ms；folders 是相对路径，其中一条就是会话所在的文件夹
运行清单：    这个会话的目录是工作区的**第一个**文件夹，不是它现在所在的那个
              （会话记录里最近的目录才是卡片上显示的那个）
```

**探查状态库**（两个都包含这个文件夹的工作区，各查一次）

```text
工作区 A：Anthropic.claude-code（170 字节）、编辑器标签页状态——都没提到这个会话
工作区 B：memento/workbench.parts.editor（33,641 字节）提到了；Anthropic.claude-code（777 字节）也提到了
```

**修复后的演算**（真实的窗口、真实的记录；聚焦 / 发链接 / `code` 换成记账的替身）

```text
vscode record: 8 windows in 14 ms
owners（按路径）: 2 个多文件夹工作区（6 个文件夹的、7 个文件夹的）
old logic (folder name in the title) finds a window: False
start folder known: True | 按启动目录筛完还剩: 2（两个工作区的第一个文件夹相同）
vscode's own record of this session: 1 window(s) in 2 ms | 7 个文件夹的那个
dry run: 已跳到 VS Code 里的这个对话 | steps: ['focus', 'uri'] | 那个窗口的当前标签页是这个对话: True
dry run, 去掉标签页线索、并把正确的窗口排到最后: steps: ['focus', 'uri'] | 聚焦的仍是真正显示它的那个窗口: True
```

**真的跳了一次**（不带任何替身）

```text
REAL jump: True 已跳到 VS Code 里的这个对话 | took 0.41 s
vscode windows before / after: 8 8
跳完之后的窗口层叠顺序：最上面三个是桌宠自己的置顶窗口，紧接着就是那个多文件夹工作区的
窗口，它的当前标签页是这个对话
```

没有新开窗口，前台是对的那个。

**没有验证的部分**

- **不是从真实的详情卡上点的。** 上面的真实跳转是脚本直接调 `jump()`，会话信息用的是
  详情卡走的同一个读取函数；卡片上的按钮本身没有点过（本会话没有驱动桌面点击的手段）。
  需要用户点一次确认。
- **走 `code` 命令的路径没有实测。** 「同名窗口好几个、对话又不在前台、状态库也没记着」
  时才会走到，这次没有遇到。「VS Code 按确切的文件夹 / 工作区文件去重」是它的既定
  行为，但对工作区文件这一种（`code --remote wsl+… <x.code-workspace>`）我没有亲手试过。
- **状态库多久落盘一次没有量。** 只知道这个已经开了一阵的会话查得到。刚开的会话查不到
  时退回路径 + 标题，那条路有用例、实机演算过。
- **只在 VS Code 上验证。** Cursor / Windsurf / VSCodium 的数据目录按同样的结构去读，
  本机没装，没有试。
- 本机（非 WSL）的多文件夹工作区、界面语言不是英文时的标题，只有用例覆盖。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests`、`git diff --check` | 通过 |
| 红 → 绿 | `pytest -q tests/test_session_jump_workspaces.py` | 第一批 18 条写在实现之前，当时整份文件因为缺 `OpenWorkspace` 导入失败，没有逐条的红；根因本身在实机上先复现过（§五「根因的现场」）。之后三批是先红后绿：并列情况 1 条（与实现同批）；启动目录 2 条 `2 failed, 20 passed` → 通过；状态库 4 条 `4 failed, 22 passed` → 通过。最终 `26 passed` |
| 聚焦 + 相关 | 新文件 + `test_session_pet_details` `test_session_custom_title` `test_session_history_service` `test_claude_session_history` | 132 passed（加状态库那一批之前）；之后新文件与 `test_session_pet_details` 重跑 `61 passed` |
| 受影响时序族满载 3 遍 | — | 不适用：都是纯函数与注入的替身，没有真实线程或等待 |
| 全量 | `python -m pytest -q -p no:cacheprovider`（`QT_QPA_PLATFORM=offscreen`，`APPDATA` 指向临时目录；隔离的 git worktree，`a44eacd` 加本改动） | `5 failed, 5116 passed, 11 skipped in 446.94s`，在最终的代码上运行。5 个失败都是这台机器上固定的环境性失败（路径超 260、两条子进程按 cp1252 打印中文、真实第二进程、多显示器负原点），与工作简报那份报告里记的是同一批。这次运行之后只新增了本报告与索引登记，`tests/test_pr_report_discipline.py` 另外单独跑过 |

## 七、已知限制与后续

- 状态库和窗口清单都是 VS Code 的内部格式（2026-10-12 实测所见，VS Code 没有承诺不变）。
  格式变了这两条线索会读不到，行为退回原来的「按文件夹名找标题」，不会出错。
- 归属完全分不清时（几个候选、对话不在前台、状态库没记着、启动目录也一样）取最近用过
  的那个候选，可能不是对的。
- 会话开在侧边栏而不是编辑器标签页时，标签页状态里没有它，只能靠插件状态那一项（1 分）
  和路径。
- 终端里的会话没有用状态库这条线索（它不是 VS Code 的标签页）。
- 每次跳转都重读一遍记录，没有缓存。15 ms 不值得为它引入失效问题。

## 八、风险与回滚

- **影响面**：「跳到对话」和「最近的对话 → 在 VS Code 里打开」。VS Code 的记录读不到
  时两者行为与原来一致。
- **配置 / 落盘**：无新增配置，不写任何文件。
- **回滚**：`git revert` 后重启桌宠。
