# PR 报告：点会话小鱼直接切到那个对话（Claude 桌面版 / Windows Terminal）

> **基线**：`b4cbe109`
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-28
> **提交**：`ad083581`
> **范围**：实现 2 个文件 + 文案 2 个 + 测试 2 个（新）

## 一、核心特性

点会话小鱼（或岛里的会话卡片）会调 `claude_session_jump.jump`。原来只认两种会话：VS Code 插件里的会话，能聚焦到它的标签页；其余的都当成终端，只把宿主窗口调到前台，提示「具体标签页要自己选」。

| # | 会话在哪 | 原来 | 现在 |
|---|---|---|---|
| 1 | Claude 桌面版（Code 标签页） | 进程链往上第一个有窗口的祖先是桌面版本身，被当成终端：只调窗口、提示自己选 | 打开桌面版自己的会话外链 `claude://claude.ai/epitaxy/<hostSessionId>`，**直接切到那个对话**；打不开时退回原来调窗口的做法 |
| 2 | Windows Terminal | 调到前台、提示自己选 | 调到前台后，用 UI 自动化按会话标题 / 会话名找到标签页并**选中**；认不出照旧提示自己选 |
| 3 | 别的终端、VS Code 内置终端 | 调到前台 | 不变（标签页从外面够不着） |

**红线 / 不变量**：

- 桌面版 id 只收 `^local_[A-Za-z0-9-]{1,64}$`，和 Claude 4.29 深链接处理器自己的校验一样；不像 id 的不拼链接。
- 选标签页时，WSL 发行版名不当线索：它会对上随便哪个 `Ubuntu-…` 标签页。
- UI 自动化出错一律退回「自己选」，不报错、不影响窗口已经调到前台这件事。

## 二、修改文件说明

`git diff --numstat b4cbe109 ad083581`：

| 文件 | 增删 | 改了什么、为什么 |
|---|---|---|
| `pet/claude_session_info.py` | +9 / −1 | 新常量 `ENTRY_DESKTOP = "claude-desktop"`。`apply_registry` 从运行清单 `~/.claude/sessions/<pid>.json` 里取 `hostSessionId`，按形状校验后记到 `detail.extra["host_session"]`：这是桌面版那边的会话 id，没有它就没法定位对话。模块说明同步 |
| `pet/claude_session_jump.py` | +74 / −6 | ① `jump` 开头：入口是 `claude-desktop`、并且有 `host_session` 时，打开 `claude://claude.ai/epitaxy/<id>`，成功就返回；② 新纯函数 `pick_tab(names, hints)`：去掉 Claude Code 加在终端标题前的状态符号（`✳`、转圈的盲文点）后，名字等于线索的优先，其次是含线索的，线索至少 3 个字；③ `select_terminal_tab(hwnd, hints)`：UIA `ElementFromHandle` → 找 `TabItem` → `SelectionItemPattern.Select()`；④ `_jump_terminal` 对 `windowsterminal.exe` 调它，`jump` 新增可注入参数 `select_tab`（测试替身用）；模块说明同步 |
| `pet/locale/zh.json` / `en.json` | +2 / −0 各 | 两句新的结果文案：已跳到 Claude 桌面版里的这个对话 / 已切到终端里这个对话的标签页 |
| `tests/test_session_jump_desktop.py`（新） | +73 / −0 | 运行清单里的 `hostSessionId` 收 / 不收（空、`local_../../x`、`session_…`）；桌面版会话只打开外链、不调窗口；没有 id 走老路；外链打不开就退回调窗口。修前三例红：`host_session` 没取、外链没开、文案键不存在 |
| `tests/test_session_jump_terminal_tab.py`（新） | +71 / −0 | `pick_tab`：状态符号、全等优先、标题对不上用会话名、都对不上、太短的线索；Windows Terminal 调到前台后选标签页；认不出保留旧文案；WSL 不拿发行版名当线索；别的终端不碰标签页。修前十例全红：函数与参数不存在 |

没有改动：VS Code 插件那条路、WSL 找终端窗口的逻辑、小鱼与岛的界面。

## 三、性能分析

**方法**：在仓库根目录跑 `.venv\Scripts\python.exe`，计时用 `timeit` 或 `time.perf_counter`。环境：Windows 11 Pro 26300，Python 3.13，Claude 桌面版 4.29。

| 指标 | 实测 | 触发频率 |
|---|---|---|
| `apply_registry`（多一次正则校验） | 1.68 µs / 次（10 万次均值） | 读会话详情时一次；原有路径 |
| `pick_tab`（4 个标签页、2 条线索） | 1.60 µs / 次（10 万次均值） | 每次点 Windows Terminal 里的会话小鱼一次 |
| `select_terminal_tab`，真实 Windows Terminal 窗口 | 认不出 89 ms，选中 39 ms（各 1 次；首次含加载 UIA 类型库） | 同上，在跳转的后台线程里 |
| `open_uri("claude://claude.ai/epitaxy/…")` | 中位 75 ms、最大 192 ms（n=10） | 每次点桌面版会话的小鱼一次，后台线程 |

**结论**：

1. **稳态开销**：没有。新代码只在用户点小鱼时运行，没有新增定时器或轮询。
2. **新路径的成本**：
   - 桌面版会话：一次 `ShellExecute`（约 75 ms），替掉了原来的「枚举窗口 + 读进程链 + 调窗口」。
   - Windows Terminal 会话：在原有流程之外，多一次 UIA 查询，约 40–90 ms。
   - 两者都在原本就是后台的跳转线程里。
3. **新的系统调用 / 磁盘 / 网络 / 线程**：
   - 系统调用：`ShellExecute`（`claude:` 协议），以及 UIA 的 COM 调用。COM 在调用它的线程里初始化、用完就释放。
   - 不碰磁盘：运行清单原来就在读。
   - 不联网，不新增线程。
4. **内存**：不新增缓存；UIA 对象在函数返回时释放。

## 四、实机运行记录

本机：Claude 桌面版 4.29（商店版），桌宠从源码运行（`run.bat`）。

**排查**：
- 桌宠日志里，点这个会话的小鱼每次都记为 `会话跳转 agent=claude session=7b58c690 ok=True：Switched to the terminal window (pick the tab yourself)`。
- 会话的 transcript 里 `entrypoint` 是 `claude-desktop`。
- 运行清单 `~/.claude/sessions/38428.json` 里有 `"entrypoint":"claude-desktop"` 和 `"hostSessionId":"local_c811…"`，正是桌面版会话元数据里外链 `claude://claude.ai/epitaxy/local_c811…` 用的那个 id。
- 读真实数据：`si.load(SessionDetail(session_id="7b58c690-…"))` 得到 `claude-desktop`、`alive=True`、`host_session=local_c811…`。

**桌面版**：桌宠用修复版重启（pid 23888）后，用户点这个会话的小鱼，**切到了这个对话**。日志 `pet-23888.log`：

```
2026-10-28 18:15:10,124 INFO 会话跳转 agent=claude session=7b58c690 ok=True：Jumped to this conversation in Claude Desktop
2026-10-28 18:15:15,385 INFO 会话跳转 agent=claude session=7b58c690 ok=True：Jumped to this conversation in Claude Desktop
```

**Windows Terminal**：本机当时开着 1 个 Windows Terminal 窗口、1 个标签页（`Ubuntu-24.04`）。UIA 读得到标签页的名字，`SelectionItem` 可用。直接调 `select_terminal_tab`：线索对不上返回 `False`（89 ms），线索为 `Ubuntu-24.04` 时选中、返回 `True`（39 ms）。

**没在实机验证的**：当时没有 Claude Code 跑在 Windows Terminal 里，所以没看到它设的标签页标题，也就没确认它和会话标题逐字一致。逻辑上有两层兜底：标题对不上时用会话名去认；都认不出时提示自己选，不会选错到别的标签页上——除非别的标签页名字里恰好含有这个会话的标题。下次有终端里的 Claude Code 会话时点一次就能确认。

**测试**：新增两个文件共 17 例，修前全红、修后全绿；跳转、架构、文案相关测试 53 例通过；ruff 通过。全量结果见 PR 描述。
