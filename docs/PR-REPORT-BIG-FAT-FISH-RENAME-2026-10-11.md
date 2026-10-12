# PR 报告：程序改名 dsh-pet-standalone → big-fat-fish

> **基线**：`e944855`（feat(chat): 本地知识库）
> **分支**：`feature/claude-session-fish`　**日期**：`2026-10-11`
> **范围**：53 个文件（实现 14、测试 11、打包与 CI 13、工具 3、文档 12 含本报告）
> **关联**：仓库与本机文件夹此前已改名 BigFatFish，程序在系统里的名字当时没动
> （见 [`PR-REPORT-BIGFISH-AUTOSTART-README-ASSETS-2026-10-11.md`](PR-REPORT-BIGFISH-AUTOSTART-README-ASSETS-2026-10-11.md)）

## 一、核心特性

程序在系统里一直沿用上游的名字 `dsh-pet-standalone`：数据目录、钥匙串服务名、开机自启
项、打包产物名、日志器名都是它。用户要求全部改成 `big-fat-fish`。

改一个字符串很容易，难在这个名字已经**写进了程序之外的四个地方**，升级的人不能因此丢
东西：

| # | 旧名字写在哪 | 不处理的后果 | 处理方式 |
|---|---|---|---|
| 1 | 数据目录 `%APPDATA%\dsh-pet-standalone[-变体]` | 设置、聊天会话、知识库副本、会话历史「消失」 | 首次启动整目录改名；新目录已存在时逐项搬 |
| 2 | 钥匙串服务名 | API Key、GitHub Token 读不到，对话 401 | 新名字下读不到时回旧名字找，找到就抄过来 |
| 3 | 开机自启项（注册表值名 / plist / .desktop） | 新旧两条并存，开机启动两次 | 属于本程序的旧项换成新名字 |
| 4 | Claude Code 钩子命令里的事件文件路径（`~/.claude/settings.json`，含 WSL 里那份） | 钩子继续往旧目录写，会话小鱼收不到事件 | 迁移后留待办标记，联动管理器把已注入的钩子改到新路径 |

**红线 / 不变量**

- 迁移只做一次，且**绝不覆盖新数据**：新目录已有 `config.json` 就不动
  （`test_fresh_installs_and_already_migrated_users_are_left_alone`）。
- 钩子只**更新**已经注入过的，从不因为迁移而新装（注入要用户同意）
  （`test_hooks_are_never_installed_by_a_refresh`）。
- 平时的配置应用不读写用户的 `~/.claude/settings.json`，只有迁移留下标记时才动
  （`test_without_a_migration_the_link_manager_never_touches_the_hooks`）。
- 别的安装（另一份检出、另一个变体）写的旧自启项不碰
  （`test_an_old_entry_that_belongs_to_another_install_is_not_touched`）。
- 旧钥匙串条目不删，回滚到旧版本还读得到。

**没有改的名字**（它们是别的字符串，不是 `dsh-pet-standalone`）：与 DSH 插件约定的桥目录
`dsh-pet-bridge`、环境变量 `DSH_PET_*`、文件名 `packaging/dsh-pet.iss`、安装包的 AppId
GUID（保持不变，已安装的用户仍按同一个程序升级）。

## 二、修改文件说明

增删取自 `git diff --numstat`（相对 `e944855`），写作「+增 / −删」。

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/config.py` | +72 / −7 | `APP_DIR_BASE = "big-fat-fish"`、`LEGACY_APP_DIR_BASE`；`_app_dir_name(base)` 同时给出新旧两个目录名。新增 `migrate_legacy_app_dir(base)`（见 §三）与待办标记 `HOOKS_REFRESH_MARKER`。`Config.__init__` 先调它。既有的「变体从共用目录继承配置」现在认新旧两个共用目录 |
| `pet/app.py` | +11 / −5 | `main()` 在算出配置目录、抢进程门锁文件**之前**先迁移；启动日志与启动失败对话框改名；启动时调 `adopt_legacy_entry()` |
| `pet/autostart.py` | +73 / −16 | 标识改为 `big-fat-fish` / `com.limincode.big-fat-fish`；`KNOWN_VALUE_NAMES` 覆盖新旧各 5 个变体名；新增 `adopt_legacy_entry()` 与 `_win_command_is_ours()`；`is_enabled()` 查不到新名字时先尝试收编旧项 |
| `pet/chat/models.py` | +13 / −2 | `SecretStore`：默认服务名 `big-fat-fish`；`get` 在新名字下为空时读旧服务名并抄到新名字下 |
| `pet/agent_link.py` | +72 / −3 | `ClaudeCodeMonitor.refresh_hooks()`；`AgentLinkManager._refresh_moved_hooks()`（本机直接改，WSL 放后台线程，失败留标记下次再试）与 `wait_for_hooks_refresh()`；发现同机其它变体时两个目录前缀都找；日志器改名 |
| `pet/catalog.py` | +10 / −7 | 外部角色目录的兜底列表加上改名前的目录，老用户放进旧目录的角色仍能找到 |
| `pet/harness_launcher.py` | +2 / −2 | 取不到配置模块时的默认目录名 |
| `pet/chat/session_store.py`、`dsh_state.py`、`multi_window_shared.py`、`self_talk_voice.py`、`settings_music.py`、`vision.py`、`window_alerts.py` | 共 +10 / −10 | 只改日志器名 `getLogger("big-fat-fish")` |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_app_rename_migration.py`（新增） | +395 / −0 | 22 条：命名 2、数据目录 6（整目录搬、Config 读到迁移后的设置、全新安装与已迁移不动、半建的新目录逐项搬、旧路径事后被写出不重复迁移、变体从共用目录继承）、钥匙串 2、开机自启 5、同机变体发现 1、旧目录里的角色 1、钩子路径 5 |
| `tests/test_autostart.py` 等 10 个既有测试文件 | 共 +40 / −40 | 字符串里的旧名字换成新名字（这些测试断言的是「变体互不影响」等行为，名字只是数据） |

### 打包、CI、工具

| 文件 | 增删 | 改动 |
|---|---|---|
| `.github/workflows/build-{windows,macos,linux}.yml`、`republish-assets.yml` | 共 +18 / −18 | 产物名、上传名 |
| `packaging/dsh-pet.iss`、`packaging/pet_entry.py` | +10 / −10 | 安装包短名、可执行文件名、显示名、默认安装目录名 |
| `scripts/build_onedir.ps1`、`build_macos.sh`、`build_linux.sh` 与 4 个校验脚本 | 共 +15 / −15 | 变体名表、示例路径 |
| `tools/mem_run.py`、`ext_ws_probe.py`、`asset_pipeline/install_step05.py` | +8 / −8 | 数据目录路径 |

### 文档

`README.md`（+1 / −1，「与上游的关系」一节说明新名字与迁移；**下方保留的上游文档原文没有
改**，那里的 `dsh-pet-standalone…` 在本项目对应 `big-fat-fish…`）；描述当前路径的 8 份参考
文档（`DEV-HANDOVER`、`ONEDIR_PACKAGING`、`STABLE_BUILDS`、`AGENT_LINK_PROTOCOL`、
`PROJECT_HANDOFF`、`AGENT_LINK_LIVE_TEST`、`NETWORK-PROXY-AND-VPN`、
`PERSONA-PHRASES-PRESET-STORAGE`）与 `注意事项.txt` 里的旧名字换成新名字；本报告与
`docs/INDEX.md`。

**故意没动**：带日期的历史记录——各份 `PR-REPORT-*`、`RELEASE-v4.2.x`、
`BUILD_ARTIFACTS-2026-08-22`、`UPSTREAM-INTEGRATION-2026-08-26` 等 20 多份。它们记的是当时
的事实，改了就不再是记录。同日的 [`PR-REPORT-GITHUB-CONNECTOR-2026-10-11.md`](PR-REPORT-GITHUB-CONNECTOR-2026-10-11.md)
里出现的 `%APPDATA%\dsh-pet-standalone\` 与钥匙串服务名也属此类，现在对应新名字。

## 三、实现要点

**数据目录迁移**（`config.migrate_legacy_app_dir`）

```text
新目录已有 config.json，或旧目录没有 config.json → 什么都不做
新目录不存在 → os.replace(旧, 新)            一次系统调用，原子
            └ 失败（旧目录里有文件被占用）→ 走下面
新目录已存在 → 逐项 os.replace；失败的项退回复制；新目录里已有的同名项保留
             config.json 最后搬（它是「完成」标记，中途被打断下次接着搬）
成功 → 在新目录写待办标记 agent-hooks-refresh.pending
```

**调用时机是关键。** `main()` 里配置目录先被用来放进程门的锁文件和日志，那时还没有
`Config` 对象。如果迁移只放在 `Config.__init__`，新目录会先被建出来，整目录改名就走不通
了。所以 `main()` 在第一次碰配置目录之前显式调一次；`Config.__init__` 里再调一次，覆盖
设置窗口等不经过 `main()` 那段的进程。

**钥匙串按需迁移。** 钥匙串没有「列出某服务下所有条目」的通用接口，所以不做一次性搬运，
而是读的时候顺手抄：新名字下为空 → 读旧名字 → 有就写到新名字下。

**钩子为什么要单独处理。** 钩子只在用户打开联动、点了同意时写入一次，之后启动不刷新；
命令里是事件文件的绝对路径。迁移后必须有人把它改掉。约束是：

- 不能在每次启动、每次应用配置时都去读 `~/.claude/settings.json`——那是用户的文件，测试
  里一个临时配置目录就可能把真机的钩子改到临时路径上。所以用**待办标记**把刷新限定在
  「刚迁移过」这一种情况。
- WSL 里那份要起 `wsl.exe`（发行版冷启动要几秒），只能放后台线程；没成功就留着标记。

**自启项「是不是我的」。** 旧值名 `dsh-pet-standalone` 是源码运行时各份检出共用的，所以
要看命令里的目录是不是本检出（打包版看可执行文件所在目录）。不是自己的不碰。

## 四、性能分析

**方法**：一次性脚本（会话内，未入库）在本机实测。真实数据取自迁移前的备份
（167 个文件）。环境：Windows 11 10.0.26300，Python 3.13.15，NVMe 本地盘。

| 指标 | 实测 | 归属 |
|---|---|---|
| 迁移检查，已迁移过（n=2000） | 中位 12.2 µs，p99 19.1 µs | 新增，每个 `Config()` 一次 + 启动一次 |
| 迁移检查，全新安装（n=2000） | 中位 26.7 µs | 同上 |
| 真实数据整目录改名（167 个文件，n=5） | 中位 1.40 ms | 新增，一生一次 |
| 真实数据逐项搬（新目录已存在，n=5） | 中位 29.11 ms | 新增，一生一次的退路 |
| 钥匙串读取，新名字下命中（n=50） | 中位 0.080 ms，最大 105.99 ms（第一次） | 既有路径 |
| 钥匙串读取，新旧都没有（n=50） | 中位 0.251 ms，最大 0.70 ms | 新增：多一次旧名字查询 |
| 真机启动：迁移 + 本机钩子改写 | 启动日志第一行后 60 ms 内完成（22:08:32.137 → .197） | 一生一次 |
| 真机启动：WSL 钩子改写（后台线程） | 0.66 s（.197 → .860） | 一生一次 |
| 新测试文件 | 22 条 0.5 s | — |

**结论**

1. **稳态开销**：每次构造 `Config` 多两次 `stat`（12 µs）。没存过 Key 的引用（例如没配
   视觉 Key）每次读取多一次旧名字查询（+0.17 ms）；存过的 Key 走原路径。
2. **新增路径**：迁移本身 1.4 ms（或 29 ms），加钩子改写，都只在升级后的第一次启动发生。
3. **新的系统调用 / 网络 / 磁盘 / 线程**：没有网络。磁盘上是一次目录改名、一个待办标记
   文件、一次 `settings.json` 改写。线程只有 WSL 钩子改写那一个 daemon 线程，且只在
   「迁移过 + 开着 WSL 联动」时出现。
4. **内存**：无新增常驻对象。

## 五、实机运行记录

本机真实数据（迁移前先备份）。命令是一段 PowerShell：备份 → 结束桌宠 → 用新代码启动 →
核对。

**迁移前**

```text
before: old exists=True new exists=False
before: hooks mentioning old path=18 new path=0
backup: %APPDATA%\dsh-pet-standalone-backup-2026-10-11.zip (1.4 MB), entries in old dir: 167
```

**启动后（桌宠自己的日志 `pet-30912.log`）**

```text
22:08:32,137 INFO big-fat-fish 启动 (slot: 0, instance: )
22:08:32,138 INFO 已把改名前的数据目录迁移到 C:\Users\limin\AppData\Roaming\big-fat-fish
22:08:32,197 INFO Claude Code hooks 已改到新的数据目录
22:08:32,860 INFO WSL 里的 Claude Code hooks 已改到新的数据目录
```

**核对**

```text
after: old exists=False new exists=True
after: files in new dir: 169; top level: agent-events, knowledge-base, sessions, voice_chime_cache,
       claude-session-history.json, config-slot-1..3.json, config.json, overlay-active-pets.json, …
after: hooks mentioning old path=0 new path=18            ← 本机 ~/.claude/settings.json
WSL ~/.claude/settings.json: big-fat-fish 9 处，dsh-pet-standalone 0 处
config dir: C:\Users\limin\AppData\Roaming\big-fat-fish
settings: provider api-2 claude-sonnet-5 | connector True | kb True <owner>/<知识库仓库>
kb: 上次同步 2026-10-11 21:51，71 个文件。 | tools: True       ← 知识库副本跟着搬过来了
provider/api-2   | under new name before read: True  | readable: True | old kept: True
connector/github | under new name before read: False | readable: True | under new name now: True | old kept: True
autostart: big-fat-fish = cmd /c start "" /D "C:\Users\limin\Github\BigFatFish" "…\BigFish.exe" -m pet --slot 0
```

- `connector/github` 那一行正好演示了按需迁移：读之前新名字下没有，读一次之后有了。
- **钩子真的切过去了**：迁移后 46 秒，新目录的 `agent-events/claude.jsonl` 修改时间是
  22:09:18（与当时系统时间相同），而旧目录没有被重新写出来——正在运行的这个 Claude Code
  会话已经在往新路径写事件，没有重启会话。

**一处事先没料到的现象**：迁移前查注册表，自启项**已经**是 `big-fat-fish` 了，旧值不在。
原因是改完代码后跑测试时，有测试构造了真实的设置窗口，它调用 `autostart.is_enabled()`
读的是真机注册表，于是「收编旧项」在测试运行期间就对真机生效了。结果是对的（值与预期
一致），但说明 `is_enabled()` 带写副作用时测试会碰真机注册表。这类副作用此前就存在
（`is_enabled()` 里的 pythonw → BigFish 升级同样会写），本次没有改变这一点，见 §七。

**没有验证的部分**

- **打包与 CI**：没有在本机构建安装包，也没有跑 GitHub Actions。产物名的改动只经过文本
  替换和 `tests/test_bundle_slim.py`、`test_uninstall_cleanup.py` 这类读脚本内容的测试。
- **打包版的迁移**（`dsh-pet-standalone-webm-chat` → `big-fat-fish-webm-chat`）：只有
  单元测试，没有真实安装过旧版再升级。
- **macOS / Linux 的自启项收编**：只读了代码路径，没有测试覆盖，也没有真机。
- **数据目录里有文件被占用时的逐项搬**：只有「新目录已存在」的替身测试，没有真机制造
  占用。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests scripts tools`、`git diff --check` | 通过 |
| 红 → 绿 | `pytest -q tests/test_app_rename_migration.py` | 实现前 17 failed；补钩子刷新的 5 条时先 5 failed；完成后 22 passed |
| 聚焦 + 相关 | 新文件 + 被替换过名字的 10 个测试文件 + `test_agent_link` `test_architecture` `test_settings_subslot_autostart` | 通过，除两条本机环境性基线（路径超 260、多显示器负原点） |
| 受影响时序族满载 3 遍 | `tests/test_app_rename_migration.py`（含后台线程的 WSL 钩子用例，用 `Event` 与 `join` 同步，无固定等待） | 3 遍均 22 passed；当时另一轮全量套件在并行运行 |
| 全量 | `python -m pytest -q -p no:cacheprovider`（`QT_QPA_PLATFORM=offscreen`，`APPDATA` 指向临时目录） | `4 failed, 4972 passed, 11 skipped in 384.65s`，在最终的文件树上运行。4 个失败是这台机器上一直存在的环境性失败（路径超 260、两条子进程输出按 cp1252 解码、多显示器负原点），与本改动无关。运行后复查真机状态：钩子路径、注册表自启项、数据目录都没有被这次测试改动 |

## 七、已知限制与后续

- **上游合并会更容易冲突**：改名触及 53 个文件，其中打包脚本和 CI 是上游也会改的地方。
- **`is_enabled()` 有写副作用**，测试里构造真实设置窗口会碰真机注册表（见 §五）。应把
  「收编 / 升级」从查询函数里拆出来，本次没做。
- 旧钥匙串条目、迁移前的备份 zip、`~/.claude/settings.json.before-big-fat-fish-rename`
  都留在原处，需要手动清理。
- 没存过的 Key 每次读取都会多查一次旧服务名，没有「已迁移完」的终止条件。
- 历史文档里的旧名字保留，读旧报告时需要自行对应。

## 八、风险与回滚

- **影响面**：所有用户的首次启动。失败模式是「迁移没发生」（新目录是空的、看起来像全新
  安装），旧目录仍在，不会丢数据。
- **新增落盘**：新数据目录、待办标记文件（处理完即删）、钥匙串里新服务名下的条目、新的
  自启项名。
- **回滚**：`git revert` 后程序重新去找 `dsh-pet-standalone`，那时它已不存在——需要手动把
  `%APPDATA%\big-fat-fish` 改回旧名字（或从备份 zip 解压），并在联动设置里关开一次让钩子
  路径写回去。旧钥匙串条目还在，Key 不受影响。
