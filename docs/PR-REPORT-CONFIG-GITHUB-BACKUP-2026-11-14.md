# PR 报告：配置备份到 GitHub（私有仓库）与一键恢复

> **基线**：`177b256c`（Island: show the character's display name … #42）
> **分支**：`claude/awesome-hamilton-fdb816`　**日期**：`2026-11-14`
> **范围**：13 个文件（实现 8，含两份文案；测试 3；文档 2）
> **关联**：[`PR-REPORT-CONFIG-CRASH-SAFE-SAVE-2026-11-13.md`](PR-REPORT-CONFIG-CRASH-SAFE-SAVE-2026-11-13.md)（本机 `.bak` 那一层）

## 一、核心特性

2026-11-13 蓝屏把 `config.json` 写成全零，桌宠按默认值重建，所有设置丢失（包括
`agent_link.claude`，导致小鱼全冻结）。PR #40 让写盘扛得住崩溃并保留本机 `config.json.bak`，
但 `.bak` 和原文件在同一块盘上；用户要一份**机器外**的「默认配置」，坏了能很快拉回来。

**存哪儿是先和用户定的**：BigFatFish 是公开仓库，而真实配置里有本机路径（知识库克隆、图片目录）、
服务商地址和 `api_key_ref` 名字。三个方案（公开仓库放脱敏默认值 / 私有仓库放完整备份 / 两者都做）
里用户选了**完整备份进自己的私有仓库**。所以本 PR 不往公开仓库放任何配置内容，代码里也不写死
任何仓库名：仓库由用户在设置里填，留空就用「AI 与对话 → 知识库」那个仓库。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 立即备份 | 设置「常规 → 配置备份 → 立即备份」：先把表单保存到盘上，再经 GitHub Contents API 把整份 `config.json` 写进 `repo:path`（默认 `.big-fat-fish/config.json`）；远端内容一样就不提交。 |
| 2 | 从 GitHub 恢复 | 确认框后拉回备份，校验是 JSON 对象才写盘（刷盘后原子替换），当前文件留作 `config.json.before-restore`；设置窗口**不保存直接关闭**，主进程的配置 watcher 自己应用。 |
| 3 | 每天自动备份 | 开关 `config_backup.auto`（默认关）。主进程定时器每 10 分钟看一眼：满 24 小时且设置真的变了（只挪了位置不算）才上传；失败 30 分钟后重试。 |
| 4 | 启动兜底 | `Config` 构造时 config.json 和 `.bak` **都**坏了，就按状态文件记的仓库 / 路径去拉一次（8 秒超时），写回盘上并记日志；拉不到才用默认值。 |
| 5 | 防「默认值顶掉好备份」 | 按默认值重建时在状态文件记 `rebuilt_at`，自动备份暂停；只有手动「立即备份」或「恢复」成功才解除。设置里的状态行会说明。 |

**红线 / 不变量**：
- 坏的本机文件**绝不上传**（不是 JSON 对象就报错，GitHub 上的好备份不动）。
- 运行期的 `Config.reload()`（GUI 线程上的配置 watcher）**绝不碰网络**；只有构造时那一次允许。
- `.bak` 优先于 GitHub：`.bak` 能用就不发请求。
- 只备份 / 恢复主配置；`config-slot-*.json` 不参与。
- 备份里没有密钥（`Config.save` 写盘前就剥掉 api_key，密钥在系统钥匙串），但有个人路径——设置文案写明必须是私有仓库。

## 二、修改文件说明

`git diff --numstat 177b256c` + 新文件行数：

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/config_backup.py`（新） | +372 | 不依赖 Qt 的核心：`normalize`（设置归一化，路径拒 `..`、空回默认）、`target_repo`（填了用填的，否则用知识库仓库）、`backup` / `fetch` / `restore`（Contents API GET/PUT，HTTP 层可注入 `request`）、状态文件 `config-backup-state.json`（`load_state` / `mark_rebuilt`）、`fingerprint`（去掉 `rx/ry/screen_name/facing` 后的 sha256）、`needs_backup`、`describe`（设置页状态行）、`recover_at_startup`。`owner/repo` 解析抄了知识库那份规则：`Config` 构造时就要归一化，而 `chat.knowledge_base` 顶层会拉起聊天 / SDK 依赖，不该进启动路径。 |
| `pet/config_backup_sync.py`（新） | +123 | 主进程定时器 `ConfigBackupSync`（照 `KnowledgeBaseSync` 的模式）：启动后 60 秒第一次检查、之后每 10 分钟；daemon 线程上传，结果经信号排队回 GUI 线程；`stop` 让晚到的结果作废。 |
| `pet/settings_config_backup.py`（新） | +198 | 设置页这一节：开关、仓库、路径、「立即备份 / 从 GitHub 恢复…」两个按钮和状态行；`save_config_backup` 随对话框保存写回。恢复成功后置 `_saved_via_button` 再关窗——表单里是恢复前的值，照常关窗保存会把恢复冲回去。放在独立模块是因为 `modern_settings_dialog.py` 有行数预算。 |
| `pet/config.py` | +33 / −3 | 新键 `config_backup`（默认值、reload 白名单、归一化、`set` 触发归一化四处登记）；构造时 `_startup_load` 标志包住 `reload()`；损坏分支改为 `.bak` → `_recover_from_github_backup()` → 都不行就 `config_backup.mark_rebuilt`；`recovered_from` 类型放宽为 `Path | str`（GitHub 来源是一段说明文字，`_setup_logging` 照常补记）。 |
| `pet/app.py` | +13 | `AppShell._start_config_backup`：紧跟知识库同步启动定时器，只建一次，失败只记日志。 |
| `pet/modern_settings_dialog.py` | +5 / −1 | import；「常规」页加这一节；`claim` 四行进「常规」域（否则落进「待分类（开发期）」）；`_write_config` 里调 `save_config_backup`。行数 2263 → 2267，预算 2291 内。 |
| `pet/locale/zh.json` / `en.json` | 各 +32 / −1 | 31 条中英文案（`config_backup.*` 错误 / 状态，`settings.config_backup.*` 界面）。`−1` 是原最后一行补逗号。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_config_backup.py`（新） | +298 | 22 例。HTTP 层用 `FakeGitHub`（Contents API 的 GET/PUT 子集，校验 Bearer 头和更新必须带 sha）。设置归一化 / round trip、仓库回退、上传与更新、内容相同不提交、坏文件不上传、401/403/404 文案、恢复写盘并留底、恢复拒绝非配置、自动备份的时机（一天一次、只挪位置不算、失败后短重试）、启动兜底（成功、短超时、拉不到就暂停自动备份、手动备份 / 恢复解除暂停、没配过备份不碰网络和钥匙串、运行期 reload 不碰网络、`.bak` 优先）。 |
| `tests/test_config_backup_ui.py`（新） | +245 | 14 例。真设置对话框（offscreen）：四行都在、默认值、仓库占位是知识库仓库、保存 round trip、立即备份先存表单再传（上传内容含表单里刚改的值）、没仓库提示、失败显示原因并恢复按钮、恢复后关窗且不回写旧表单、取消不动；定时器：开关开且到点才备份、关着不动、回退知识库仓库、没 Token 不动、重建后暂停；`AppShell._start_config_backup` 只建一次。 |
| `tests/test_config_schema.py` | +1 | 白名单快照加 `config_backup`。 |

### 未改动

- `pet/chat/knowledge_base.py`：没把 `parse_repo` 挪出来共享（挪动会改它的 import 面），本 PR 抄了同一套规则并在注释里写明出处。
- 右键菜单 / 托盘：恢复是低频命令，只放在设置页这一处入口；按 `SETTINGS-CHANGE-GATES.md` 的「归属唯一」不复制。
- 没有做「公开仓库放脱敏默认值」那一半（用户没选）。

## 三、实现要点

- **为什么 Contents API 而不是在本地克隆里 git commit**：恢复最需要的场景是这台机器出了问题，本地克隆可能不在、不完整或有未提交改动；REST 只需要 Token，单文件 GET/PUT 也不碰用户克隆的工作区。Token 与知识库同步 / GitHub 连接器共用钥匙串里的 `connector/github`，设置页上刚填未保存的也算。
- **为什么状态放 `config-backup-state.json` 而不是 config.json**：config.json 坏了的时候还得知道去哪儿拉。状态文件写得少（备份 / 恢复 / 重建时），且同样走 `_write_durably`。
- **默认路径点开头**（`.big-fat-fish/config.json`）：Obsidian 不显示，肥鱼自己的知识库同步（`_safe_member` 跳过点开头目录）也不会把配置当笔记读进对话。
- **只挪位置不算变化**：`rx/ry` 每次拖动都存盘，不排除就等于每天一次提交、进用户知识库的 git log。
- **启动兜底的超时**选 8 秒：只有 config.json 和 `.bak` 同时坏才会走到（一年也碰不上一次），宁可多等几秒拿回全部设置；网络不通时 urllib 立刻失败，不会真等满。
- **暂停而不是信任**：网络不通 → 按默认值启动 → 第二天联网，若没有 `rebuilt_at`，自动备份就会把默认配置推上去。GitHub 有历史能找回，但用户不该需要去翻 git 历史。
- **线程模型**：设置页与定时器都是 daemon 线程做网络，结果经 Qt 信号排队回 GUI 线程；窗口中途关闭时 emit 的 `RuntimeError` 吞掉（与知识库同步一致）。

**设置准入**（`SETTINGS-CHANGE-GATES.md`）：

| 项 | 记录 |
|---|---|
| setting_id | `config_backup.auto` / `config_backup.repo` / `config_backup.path`（两个按钮是命令，不持久） |
| domain / group | 常规 / 配置备份 |
| default | `auto=False`、`repo=""`（= 知识库仓库）、`path=".big-fat-fish/config.json"` |
| capability / platform | 三端一致；需要钥匙串里有能写该仓库的 GitHub Token |
| disclosure | primary |
| commit_policy | 随设置保存（on_finish）；「立即备份」先保存再传 |
| migration | 新键，旧配置没有就取默认；脏值（字符串布尔、`..` 路径、网址形式仓库）归一化 |
| recovery | 网络 / Token 失败只在状态行和日志里报，不挡启动、不改配置；恢复前留 `config.json.before-restore` |

## 四、性能分析

**环境**：Windows 11 Pro 26300，Python 3.13.15，PySide6 6.12.0；本机配置 10,084 字节。

| 指标 | 实测 | 归属 |
|---|---|---|
| `config_backup.normalize` | 2.67 µs/次（10,000 次均值） | 新增，`Config` 构造与每次 `set("config_backup")` |
| `needs_backup`（读盘 + JSON + sha256 全路径） | 中位 0.212 ms，p95 0.352 ms（200 次） | 新增，主进程每 10 分钟一次 |
| `needs_backup`（有近期失败记录，提前返回） | 中位 0.045 ms（200 次） | 同上 |
| `Config()` 正常加载（文件完好） | 中位 0.4 ms（30 次） | 既有路径；新增只是一次 `normalize` |
| 真实一次备份请求（401 被拒，含 TLS） | 221 ms | 新增，一天至多一次 / 手动 |
| 启动兜底（文件全零、无 `.bak`、GitHub 401） | `Config()` 139 ms | 新增，只在两层本地恢复都失败时 |

方法：`PYTHONPATH=. .venv/Scripts/python.exe <脚本>`，脚本在本机临时目录，对真实配置的**副本**计时（`time.perf_counter`）。

**结论**：
1. **稳态开销**：完好配置的启动多一次 2.67 µs 的归一化；运行期每 10 分钟一次 0.2 ms 的检查（读 10 KB + 哈希），自动备份关着时连这个都不做（开关先判断）。
2. **新增路径成本与频率**：备份 ≤ 每天一次（且设置有变化才传），一次是一个 GET + 可能一个 PUT，实测约 0.2 s，在 daemon 线程上，不占 GUI 线程。启动兜底只在两层本地恢复都失败时触发，最坏 8 s 超时（只发生在网络慢而不是不通时）。
3. **新的系统调用 / 网络 / 磁盘 / 线程**：网络——GitHub API 的 HTTPS 请求（仅备份 / 恢复 / 兜底时）；磁盘——每次备份 / 恢复 / 重建写一次状态文件（~300 字节，刷盘）；线程——每次备份起一个短命 daemon 线程。常驻：一个 10 分钟 `QTimer`。
4. **内存**：常驻一个 QObject 和一个 QTimer；备份时临时持有一份配置字节（10 KB 级）。

## 五、实机运行记录

全部在本机真实 Windows 环境、真实网络上做，对象是真实配置的**副本**（`%TEMP%` 下的 scratchpad），真实 `%APPDATA%\big-fat-fish` 只读未写。私有仓库名在下面记作 `<private-repo>`。

**1. 前提：钥匙串里的 GitHub Token 现在是失效的**（探针，只打印类型不打印值）：

```
keychain token kind: ghp_ len 40
https://api.github.com/user HTTP 401 Bad credentials
https://api.github.com/repos/<private-repo> HTTP 401 Bad credentials
```

所以本机此刻**无法实测成功上传 / 拉回**——不是代码问题，是 Token 被吊销或过期（知识库同步走的也是它，同样会失败）。成功路径由 `FakeGitHub` 测试覆盖（上传内容、更新带 sha、恢复写盘）；用户换上有效 Token 后点「立即备份」即可在真机上补验。

**2. 真实备份请求的失败路径**（真实网络，401）：

```
backup error: GitHub 拒绝访问（HTTP 401）：Token 要能读写 <private-repo> 的内容（Contents: Read and write）。
elapsed_ms 221
state repo='' error_set=True backed_up_at=0.0
describe: 还没有备份过。 上次尝试失败：GitHub 拒绝访问（HTTP 401）：……
```

失败没有在状态文件里记仓库（`repo=''`），所以启动兜底不会被一次失败的备份「武装」。

**3. 设置页真机渲染**（Windows 原生平台，非 offscreen；1100×820）：「常规」页最下面出现「配置备份」一节，四行齐全；仓库填好后点「立即备份」，按钮在请求期间禁用，结束后恢复，状态行显示「失败：GitHub 拒绝访问（HTTP 401）：Token 要能读写 … 的内容（Contents: Read and write）。」并正常折行。（截图含本机路径与私有仓库名，未提交进仓库。）

**4. 启动兜底真机重演**（副本：config.json 写成全零、删掉 `.bak`、状态文件指向 `<private-repo>`）：

```
WARNING pet.config_backup 配置损坏且没有可用的 .bak；从 GitHub 备份恢复失败: GitHub 拒绝访问（HTTP 401）：……
Config() with zeroed file + GitHub fallback ms 139
recovered_from None rebuilt_at set True
needs_backup far future: False
```

拉不到时按默认值启动、`rebuilt_at` 已记、十天后的自动备份检查仍然说「不备份」——默认配置不会顶掉 GitHub 上的好备份。

**5. 没做的实机项与原因**：
- 没有重启运行中的桌宠来跑定时器：桌宠正从另一个 worktree 运行（带着别的会话尚未合并的修复），换成本分支会把那些修复从用户桌面上拿掉。定时器的判断与触发由单元测试覆盖，`AppShell` 接线有测试。
- 成功上传 / 恢复见第 1 条：需要有效 Token。

**测试**：`QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/test_config_backup.py tests/test_config_backup_ui.py tests/test_config_*.py tests/test_architecture.py tests/test_i18n.py tests/test_knowledge_base.py tests/test_island_display_name.py tests/test_modern_settings_rows_topwindow.py tests/test_settings_*.py tests/test_persona_settings.py tests/test_overlay_settings_command.py tests/test_pr_report_discipline.py -q` → **545 passed**（57 s）。红→绿：核心测试在模块不存在时收集即失败；设置页测试把 `modern_settings_dialog.py` 换回基线版本时 8 例失败、换回本 PR 后全过。`ruff check pet tests` 通过。

**为什么没跑全量**：按用户 2026-11-14 起的规矩，只跑新测试 + 受影响的测试族。本 PR 动了配置模型（`Config` 新键与加载分支）、设置对话框和 `AppShell` 启动接线，对应的族是 `test_config_*`、`test_settings_*` / 设置对话框、`test_architecture`（行数预算与退役模块）、`test_i18n`（文案键）、知识库（共用 Token 与仓库解析规则），以上已全部跑过。新测试不起真实线程（worker 内联执行），不涉及时序，因此没有做高负载复跑。
