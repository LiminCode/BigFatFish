# PR 报告：右键菜单「Claude Desktop」「Claude Code（WSL）」两条入口

> **基线**：`998b7b7`（feat(menu): 右键菜单「YouTube Music」）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-15
> **范围**：10 个文件（实现 6、测试 3、文档 1）
> **关联**：[`PR-REPORT-YOUTUBE-MUSIC-2026-10-15.md`](PR-REPORT-YOUTUBE-MUSIC-2026-10-15.md)（本次照它的五处改动走）；
> [`PR-REPORT-WORK-BRIEFING-2026-10-12.md`](PR-REPORT-WORK-BRIEFING-2026-10-12.md)（WSL 里那个账号的 Claude Code 是什么）

## 一、核心特性

肥鱼自己的聊天走个人 API key，工具只有本地知识库与 GitHub 只读连接器；用户想随时一键拉起
「全功能」的 Claude——商店版 Claude Desktop，以及 WSL 里登录着另一个账号的 Claude Code。
右键菜单加两条启动入口，放在「YouTube Music」后面，新式 / 旧式菜单都有，托盘与灵动岛不加
（用户 2026-10-15 的决定）。

起因是用户在快速对话里问肥鱼「能不能和 WSL 里的 Claude 对话」，肥鱼如实答「做不到」——
代码里确实没有那条通路（现有的 WSL 通道只有工作简报与 Slack 关注两条固定提示词的单向任务）。
用户随后决定：不做「肥鱼转发对话」，改做「一键拉起」。顺带修正一个前提：肥鱼聊天**没有**锁死
模型与 effort（模型自由填写，effort 可选到 `max`），差的是工具与账号。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 「Claude Desktop」 | `os.startfile` 拉起本机 Claude 桌面程序：老式安装器的 exe 优先，否则商店版的 `shell:AppsFolder\<家族名>!Claude`（家族名从注册表的包仓库里找，不起 PowerShell）。没装 → 置灰，提示「没找到 Claude Desktop」。 |
| 2 | 「Claude Code（WSL）」 | Windows Terminal 新开默认发行版标签，`--cd ~` 进家目录，登录 shell 起 `claude`，退出后留在 shell 里（照「最近的对话 → 在终端继续」那条命令）。没有 `wt` 退到普通控制台；没有 WSL → 置灰，提示「没找到 WSL」。 |
| 3 | 启动失败冒泡 | ShellExecute / Popen 抛 OSError 时写日志并冒一句气泡；壳的门面与 PetWindow 都有 `show_bubble`。 |

**红线 / 不变量**：不往两个程序里送任何内容（只拉起，不传提示词、不传 `--model`）；不加配置键；
不加线程；用户保存过的菜单编排按模板邻位自动补入这两项、自己的顺序不动。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/claude_launchers.py` | +123 / −0 | 新模块，零 Qt。`claude_desktop_target()`：先看 `%LOCALAPPDATA%\AnthropicClaude\claude.exe`，再枚举 `HKCU\…\AppModel\Repository\Packages` 下以 `Claude_` 开头的包全名，`_family_name` 把 `Claude_2.37337.1.0_x64__pzs8sxrjxfjjc` 转成 `Claude_pzs8sxrjxfjjc`，返回 `shell:AppsFolder\…!Claude`；`enumerate_packages` 可注入（写法照 `vscode_workspaces._registry_distros`）。`wsl_claude_argv()`：`[wt, wsl.exe, -d <默认发行版>, --cd ~, --, bash, -lic, "claude; exec bash"]`，发行版取 `wsl_distros()` 第一项（已滤掉 docker 之类）。`launch_*` 两个：`os.startfile` / `Popen(DEVNULL×3)`，失败记日志返回 False。 |
| `pet/context_menus/shared.py` | +38 / −0 | 两个叶子 `add_claude_desktop` / `add_wsl_claude_code`（紧挨 `add_youtube_music`）：建菜单时查一次目标，没有就 `setEnabled(False)` + tooltip；点击走 `claude_launchers.launch_*`，失败经 `_tell` 冒泡。经模块属性调用，测试可换。 |
| `pet/context_menus/registry.py` | +6 / −0 | 登记 `claude_desktop` / `wsl_claude_code`：标签、图标名、`MenuActionSpec`。 |
| `pet/context_menus/icons.py` | +7 / −0 | 新记号 `sparkle`（四角星，四段三次曲线），描边语言与其余图标一致，不用品牌色。WSL 那条复用 `ubuntu`。 |
| `pet/menu_templates/modern-default-v1.json` | +2 / −0 | 两个 action 节点插在 `youtube_music` 之后、`default.separator-playback` 之前，`section: playback`。 |
| `pet/context_menus/legacy.py` | +4 / −0 | 旧式菜单在 `add_youtube_music` 后加两行（`icons=False`）。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_claude_launchers.py` | +186 / −0 | 纯逻辑：老式 exe 优先、商店包 → AUMID、都没有 → 空、包名坏了 → 空；`wt` 有 / 无、发行版有 / 无、没 WSL → None 的四种 argv。菜单：模板位置与标签 / 图标名；modern 与 legacy 的 overlay 菜单点两条各启动对的程序（只记参数）；没装时两条置灰且有 tooltip；启动失败冒两句气泡；旧 PetWindow（`_LegacyHost`）也有；用户保存过的编排自动补入。 |
| `tests/test_menu_layout.py` | +10 / −1 | 三处 id 清单与两处渲染标签清单加上两项。 |
| `tests/test_desktop_pet_features.py` | +2 / −0 | 默认模板的分组标签清单加上两项。 |

### 未改动

- 托盘菜单（`overlay_shell._refresh_tray_menu` / `app._build_tray`）与灵动岛：用户决定只放右键菜单。
- `pet/config.py`：不加键。「一次性启动 X」的命令属于菜单，不属于设置（`SETTINGS-CHANGE-GATES`）。
- `tests/test_sprite_menu_parity.py`：两条在 legacy 与 overlay 都有，不需要进 `ALLOWED_EXTRAS`。
- `pet/claude_session_history.py` 的 `terminal_resume_argv`：没有抽公共函数——两条命令只有 `--cd` 与 `claude` 参数不同，抽出来反而要多一层参数；各自保持可读。

## 三、实现要点

- **商店版怎么找**：MSIX 包没有可执行路径，`os.startfile("shell:AppsFolder\\<家族名>!<AppId>")` 交给
  ShellExecute 最稳。家族名 = 包名 + `_` + 发布者 id，从 `HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages` 的子键名解析，
  本机 182 个包枚举一次 0.4 ms（见四）。`Get-AppxPackage` 要起 PowerShell（上百毫秒），不用。
  `claude://` 协议也注册了，但它打开后的行为（是否新建对话）没有文档，不赌。
- **可用性放在叶子里**：registry 的 `enabled=` / `disabled_reason` 只对 modern 生效，legacy 建造器不走它；
  叶子自己 `setEnabled(False)` 两边都覆盖，且只查一次。
- **WSL 那条不加 `CREATE_NO_WINDOW`**：要的就是终端窗口；`wt` 在跑时会在已有窗口里新开标签而不是新进程。

## 四、性能分析

**方法（可复现）**：
```
.venv\Scripts\python.exe -c "import timeit, statistics; from pet import claude_launchers as L; from pet.vscode_workspaces import wsl_distros; n=200; r=[timeit.timeit(L.claude_desktop_target, number=1)*1000 for _ in range(n)]; print(statistics.median(r), sorted(r)[int(n*0.95)], max(r)); r=[timeit.timeit(L.wsl_claude_argv, number=1)*1000 for _ in range(n)]; print(statistics.median(r), sorted(r)[int(n*0.95)], max(r))"
```
环境：Windows 11 Pro 10.0.26300，Python 3.13（仓库 `.venv`），本机包仓库 182 个商店包，n=200。

| 指标 | 实测 | 归属 |
|---|---|---|
| `claude_desktop_target()`（枚举 182 个包 + 一次 `isfile`） | 中位 0.400 ms，p95 0.544 ms，最大 0.640 ms | 新增，每次右键建菜单 1 次 |
| `wsl_claude_argv()`（两次 `shutil.which` + 读注册表发行版） | 中位 1.537 ms，p95 2.139 ms，最大 2.946 ms | 新增，每次右键建菜单 1 次 |
| 　其中 `wsl_distros()` | 中位 0.051 ms | 既有 |

**结论**：① 稳态开销无变化——不加定时器、不加线程、不在启动时做任何事；② 新增路径只在
右键建菜单时各跑一次，合计约 2 ms（p95 2.7 ms），低于 5 ms 的缓存门槛，所以不加缓存，
装 / 卸载 Claude Desktop 后下一次右键就反映出来；点击时一次 ShellExecute 或 Popen；
③ 新增系统调用：注册表枚举（右键时）、`os.startfile` / `Popen`（点击时）；无网络、无磁盘写、无线程；
④ 内存：无缓存、无常驻对象。

## 五、实机运行记录

**前提的现场复现**（2026-10-15，本机）：

```
PS> Get-AppxPackage | ? Name -match 'Claude' | select Name, PackageFamilyName
Claude  Claude_pzs8sxrjxfjjc
PS> ls $env:LOCALAPPDATA\AnthropicClaude        # 老式安装器：不存在
PS> wsl.exe -l -v                                # * Ubuntu-24.04 Running 2 ；docker-desktop Stopped
PS> wsl.exe -d Ubuntu-24.04 -- bash -lc 'which claude; claude --version'
/home/<user>/.local/bin/claude
2.1.300 (Claude Code)
```

**真实环境下两个函数的返回与一次真实拉起**（直接调模块，真实 `APPDATA` / 注册表 / PATH）：

```
target = shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude
argv   = ['…\WindowsApps\wt.EXE', 'C:\WINDOWS\system32\wsl.exe', '-d', 'Ubuntu-24.04', '--cd', '~', '--', 'bash', '-lic', 'claude; exec bash']
desktop shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude True
wsl True
# 6 秒后：新出现 8 个 claude.exe 进程（其中一个主窗口标题 "Claude"），Claude Desktop 已前置；
# WSL 侧：  56131  56126  23  pts/8  claude      ← 新终端里的新会话（VS Code 扩展里的几个会话排除在外）
# Windows Terminal 已在跑，所以新标签开在已有窗口里，没有新的 WindowsTerminal 进程
```

**用户可见行为**：改完代码按 memory 的方法重启肥鱼（只结束不含 `--settings` 的主进程），
`pet-overlay-gate.log` 多一行 `acquired pid=21572`，新进程日志无 ERROR / Traceback。
右键菜单里两条新入口要**用户自己右键**看——本机没有能点真实右键菜单的自动化工具，
菜单的构建与点击在 `tests/test_claude_launchers.py` 用真实 `OverlayShell` + 真实 `QMenu`
（offscreen）覆盖，启动函数在上面用真实环境各跑了一次。

**边界与失败路径**：「没装 → 置灰」在本机做不出真实场景（两个程序都装着），由测试
`test_entries_are_greyed_out_when_nothing_is_installed`（两种模板）覆盖；纯函数一侧用真实
PATH 探过 `wsl_claude_argv(wsl="")` → `None`。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 红灯 | `pytest -q tests/test_claude_launchers.py`（实现前） | 收集期 `ImportError: cannot import name 'claude_launchers'` |
| 静态检查 | `.venv\Scripts\ruff.exe check pet tests` | All checks passed |
| 聚焦 + 相关 | `pytest -q tests/test_claude_launchers.py tests/test_youtube_music.py tests/test_menu_layout.py tests/test_sprite_menu_parity.py tests/test_desktop_pet_features.py tests/test_vscode_workspaces.py tests/test_i18n.py tests/test_menu_music_entries_removed.py` | 250 通过，1 失败 = 基线 `test_image_directory_picker_…`（路径超 260，与本次无关） |
| 受影响时序族 | 无——本改动不含线程 / 事件循环时序 | 不适用 |
| 全量 | `python -m pytest -q -p no:cacheprovider`（offscreen，临时 APPDATA） | 见下 |
| 架构红线 | `tests/test_architecture.py`（含在全量里） | 见下 |

全量结果：`4 failed, 5272 passed, 11 skipped in 549.67s (0:09:09)`。4 个失败全是本机既有的环境性基线（`test_image_directory_picker_…` 路径超 260；`test_festival_id_guard_survives_optimize` 与 `test_real_second_process_refused_on_overlay_topology` 子进程输出按 cp1252 解码；`test_capture_window_rect_coordinates_and_clamping` 多显示器负原点），改动前后同一组，`tests/test_architecture.py` 在其中通过。

## 七、已知限制与后续

- Claude Desktop 商店版的「打开后新建一个对话」没做：只前置程序。`claude://` 协议若日后有文档
  可以接。
- 「最近的对话」不识别 Claude Desktop 的会话（它不写 `~/.claude/projects`）。
- 用户点名**以后再聊**的话题，本次不碰：往交互式 Claude Code 的 TUI 里塞字；会话小鱼要么做成
  Claude Desktop 那样、要么整个移除。
- WSL 入口固定在家目录；想在工作区目录起 claude 可以加子菜单（用户本次选了一键）。

## 八、风险与回滚

- 影响面：右键菜单两条新项与一个新记号；不动配置、不动托盘、不动灵动岛、不动任何常驻路径。
- 回滚：`git revert` 即可。用户保存过的菜单编排里若已补入这两个 id，回滚后
  `menu_layout` 会把未登记的 id 当未知项丢弃（既有行为），没有落盘残留。

---

## 第二轮修正：Windows Terminal 把分号当子命令分隔符

### 现场（用户 2026-10-15 实机截图）

点「Claude Code（WSL）」后 Windows Terminal 开了**两个**标签：第一个 `C:\WINDOWS\system32\wsl.ex…`
（claude 其实在里面起来了），第二个标题 `exec bash`，内容：

```
[error 2147942402 (0x80070002) when launching `" exec bash"']
The system cannot find the file specified.
```

根因：`wt` 把命令行参数里的 `;` 当成它自己的「子命令分隔符」，**哪怕在引号里**。
`bash -lic "claude; exec bash"` 被劈成 `wsl.exe … bash -lic "claude` 和 `" exec bash"` 两个
子命令。第一轮实机记录里「WSL 侧 pts/8 有 claude」就是第一个标签，错误标签当时没看到。
现成的「最近的对话 → 在终端继续」（`claude_session_history.terminal_resume_argv`）用的是
同一写法，有同样的毛病，一起修。

### 修法与验证

wt 文档的转义是 `\;`：先用无害命令实测——

```
wt.EXE wsl.exe -d Ubuntu-24.04 --cd ~ -- bash -lic "touch /tmp/bff-semi-test\; exit"
$ ls /tmp/bff-semi-test*      → 只有 /tmp/bff-semi-test（没有 "bff-semi-test;"，也没有 /tmp/exit）
```

说明 wt 把 `\;` 还原成 `;` 再交给 wsl.exe，bash 收到的是真正的分隔符。**只有经 `wt` 的那条
路转义**；`cmd /c start` 不经 wt，照原样。

| 文件 | 增删 | 改动 |
|---|---|---|
| `pet/claude_launchers.py` | +19 / −3 | `NEW_SESSION_SCRIPT` 常量；`wt_script()` 把 `;` 写成 `\;`（docstring 记着根因与实测）；`wsl_claude_argv` 的 wt 分支用它，cmd 分支不用。 |
| `pet/claude_session_history.py` | +7 / −3 | `terminal_resume_argv` 的 WSL 分支同样处理（import `claude_launchers`，无循环：`-W error::SyntaxWarning` 下三模块导入正常）。 |
| `tests/test_claude_launchers.py` | +21 / −8 | 期望值拆成 `SCRIPT` / `WT_SCRIPT`；新增 `test_the_semicolon_is_escaped_only_on_the_windows_terminal_path`（wt 路径里不许剩裸分号、cmd 路径原样）。 |
| `tests/test_claude_session_history.py` | +3 / −1 | 「在终端继续」的 WSL 期望改成转义后的，并多断言 cmd 退路不转义。 |

修后真实拉起一次（真实 PATH / 发行版）：

```
argv[-1] = claude\; exec bash
launched True
# 8 秒后 WSL 侧：
 125523       7 pts/10   claude                      ← 新标签里的新会话
 125236       7 bash -lic claude; exec bash          ← bash 收到的已经是去掉转义的分号
```

bash 的参数是完整的 `claude; exec bash`，不再有第二个 `exec bash` 标签。肥鱼已重启
（`acquired pid=25652`，日志无 ERROR）。

门：ruff 全过；`pytest -q tests/test_claude_launchers.py tests/test_claude_session_history.py
tests/test_session_history_service.py tests/test_youtube_music.py tests/test_sprite_menu_parity.py`
110 通过。第一轮全量之后只改了这两条命令行的拼法与其测试，不重跑全量。

### 教训

- 往 `wt` 传 shell 脚本，`;` 必须 `\;`，引号不保护。
- 第一轮「实机运行记录」只看了进程表，没看终端窗口本身——多出来的错误标签是用户发现的。
  以后凡是「拉起一个窗口」的功能，实机记录要包含窗口 / 标签的观察，不能只数进程。

---

## 第三轮调整：新会话开在 `~/workspace`，不开在家目录

### 现场

修完分号后用户点入口，每次都停在 Claude Code 的「Accessing workspace: /home/limin … Yes, I trust
this folder」上。查 WSL 里的配置：Claude Code 2.x 真正在写的是 `~/.claude/.config.json`
（`~/.claude.json` 停在 8 月 21 日），信任按目录记在 `projects[<路径>].hasTrustDialogAccepted`；
`/home/limin` 是 `False`，另外 8 个目录（含 `/home/limin/workspace`）是 `True`。没有「信任所有目录」
的开关（公司下发的 remote-settings 也只有 `permissions.deny`）。

用户的决定：不信任整个家目录（等于放开家目录里的一切），改成在已经信任过的 `~/workspace` 开新会话。

### 改动

| 文件 | 改动 |
|---|---|
| `pet/claude_launchers.py` | 常量 `WSL_START_DIR = "~/workspace"`（注释记着为什么不用家目录），`wsl_claude_argv` 用它。`wsl.exe --cd` 认 `~/…`：本机 `wsl.exe --cd ~/workspace -- pwd` → `/home/limin/workspace`。 |
| `pet/context_menus/shared.py` | 叶子 docstring 改口。 |
| `tests/test_claude_launchers.py` | 期望里的 `--cd ~` 改成 `--cd ~/workspace`；用例名改成 `…_in_the_trusted_workspace_folder`。 |

不加配置项：目录是用户点名的一个固定值；要改目录是改一个常量。若以后想按人配置，再走
`SETTINGS-CHANGE-GATES`。

### 实机

```
argv = wsl.exe -d Ubuntu-24.04 --cd ~/workspace -- bash -lic claude\; exec bash
launched True
$ pwdx 133187 127806 125523
133187: /home/limin/workspace    ← 这次（pts/13，21 秒）
127806: /home/limin              ← 之前家目录版本的两次
125523: /home/limin
```

新会话的工作目录是 `/home/limin/workspace`，该目录已信任，不再弹对话框。肥鱼已重启
（`acquired pid=10404`，日志无 ERROR）。门：ruff 全过；`tests/test_claude_launchers.py` +
`tests/test_claude_session_history.py` 63 通过。
