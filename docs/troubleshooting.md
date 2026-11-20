# 排障手册

> 先按症状找到归属的文档；跨功能的几类问题（联网、测试套件原生崩溃、WSL 共享、无界面 Claude Code 的连接器）直接写在本文。
> 日志在 `%APPDATA%\big-fat-fish\pet-<pid>.log`。

## 按症状找

| 症状 | 先看 |
|---|---|
| 界面回到最初的样子、设置全丢、API Key 要重填 | [配置与数据](config-and-data.md)：先找 `config.json.corrupt-*` 和 `.bak` |
| 某个联网功能「昨天还好好的」：歌词没了、语音不出声、连接图标变红 | 本文「联网功能」 |
| 语音报时没声音、气泡报「语音合成失败」 | [台词、人设与语音](persona-and-voice.md)，再看本文「联网功能」 |
| 会话小鱼不出现、一直「工作中」、活着的对话显示成冻结 | [会话小鱼](session-fish.md)：先看 `agent_link.claude` 是否开着、hooks 是否还在 |
| 「跳到对话」跳错窗口、新开了窗口、开了终端 | [跳到对话](session-jump.md)：升级 VS Code / Claude Code 后先核对「外部格式依赖」 |
| 灵动岛不见了、位置不对、被盖住、卡片显示不全 | [灵动岛](island.md) |
| 通知弹窗看不见、缺一块、点了没反应、正文不全 | [通知](notifications.md) |
| 右键菜单圆角外发黑、菜单项不见了 | [设置与右键菜单](settings-and-menu.md) |
| 新加的设置项不见了、刚配的值没了 | [设置与右键菜单](settings-and-menu.md)：先问是不是有旧的设置窗口还开着 |
| 界面文字没跟着语言切换 | [界面语言](i18n.md) |
| 工作简报某一节读不到、笔记推不上去、Slack 关注重复提醒 | [公司侧助理](work-assistant.md) |
| 简报的 Jira 一节说「连接器被拒、需要重新登录」，重新认证了 Atlassian 插件还是不行 | 本文「无界面 `claude -p` 里的连接器」 |
| 个人简报失败、开了连接器后对话全部 400 | [个人侧助理](personal-assistant.md) |
| 蒸馏的提案接受不了、候选数不对 | [会话记忆蒸馏](memory-distill.md) |
| 关机 / 注销时弹 `0xc0000142` | [架构与红线](architecture.md) 的「会话结束冻结」 |
| 连点鱼几秒没反应，日志里成串 `frameseq 预取超时` | [与上游的关系](upstream.md) 的「帧序列档位」 |
| 全量测试随机 access violation | 本文「测试套件原生崩溃」 |
| 启动后刷一百多条 `WinError 206` 警告 | 从很深的路径启动，帧序列缓存目录路径超长。把工作区放到 `.claude/worktrees/<短名>` 这类短路径下 |
| 「回到右下角」闪回原地 | 只 `move()` 不够：移动动画和拖动物理的定时器还在写旧坐标，要先停掉它们再移动并保存 |

## 联网功能：先怀疑系统代理 / VPN

肥鱼的联网请求都跟随 Windows 的系统代理（`urllib` 自动读注册表和环境变量）。开着 VPN 时，有的功能变慢到超时，
有的反而只有走代理才通，不能一概而论。

| 功能 | 出口 | 代理下的表现 |
|---|---|---|
| 歌词取词 | `pet/music_lyric.py` | 走代理时三个源都要 20～40 秒，超过 8 秒超时。**代码里固定直连**（`_build_opener()` 用空的 `ProxyHandler`），唯一一处不跟随系统代理的 |
| 语音合成（edge-tts） | `pet/voice_chime_service.py` | 直连和走代理都能用；海外网络需要代理，所以不绕过 |
| 本机服务：本地语音、DSH 联动、端口探活 | `127.0.0.1` | 代理把 localhost 也接管时全部失败。代理设置里必须保留 `localhost;127.*` 绕过 |
| 对话、灵动岛连接图标 | 用户自己配的端点 | 取决于端点在哪；慢代理下一直等到超时，观感是「点了没反应」。连接图标红了先看悬停提示，区分是 Key 的问题还是网络的问题 |
| 点击音效 | 不联网 | 与代理无关 |

**30 秒判断是不是代理**：

```powershell
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" | findstr /i proxy
python -c "import urllib.request; print(urllib.request.getproxies())"
```

关掉系统代理重做同一个操作，立刻恢复就是它。要量化某个端点，用 `urllib.request.ProxyHandler({})`（直连）
和 `ProxyHandler({"https": "<代理地址>"})` 各发一次同样的请求比耗时。

**取舍**：逐功能决定走不走代理，不做全局绕过，也不改用户的代理设置。推荐用户用分流（规则）模式并保留
localhost 绕过。已知没做：只有代理能出网的用户，歌词会取不到（可以做成直连失败后走代理兜底，
代价是失败路径从 9 秒变成约 18 秒）。

## 测试套件原生崩溃

**现象**：Windows + offscreen 下跑全量，随机位置出现 `0xC0000005`（access violation）或 `0xC0000374`
（堆损坏）。Python 显示的「当前测试」通常不是肇事者，崩溃发生在 Qt 原生对象释放或事件派发的时候。

**机制**：pytest 进程里 `QApplication` 是共享的。前面的测试留下没有父对象的 `QWidget` / `QMenu`、延迟删除任务、
还在跑的线程或 reader，后面的测试一处理事件就踩到已释放的对象。普通的 `close()` 不等于 C++ 对象已经销毁，
`processEvents()` 也不保证处理完延迟删除。

**排查顺序**：

1. `python -X faulthandler -m pytest -x -q` 重跑并保留完整输出，否则崩溃位置记不下来。
2. 不要把崩溃时的测试直接当成肇事者。往前找：它之前谁创建了没有父对象的窗口、菜单、`QThread`、`QTimer`、ffmpeg reader。
3. 查有没有全局的 `sendPostedEvents`、对共享应用的 `processEvents()` 清理，或没人接手的 `deleteLater()`。
4. 修法：把真实的原生边界换成 Python 层的 seam，或者由 owner 定向同步销毁。产品代码的 owner 必须在自己的关闭入口
   停掉线程、定时器、reader 和外置窗口，测试的 teardown 不能代替它。
5. 先跑相关组合，再跑主套件，最后才跑跨进程 / 多线程的压力测试。

**已知的两个事实**：

- 往 `tests/conftest.py` 加 autouse 夹具会把这个潜伏的崩溃引出来（见 [开发指南](development.md)）。
- 不改任何东西它也会间歇出现。全量崩了先怀疑它，再怀疑自己的改动；要下结论就在改动前的提交上用同样的条件重跑。

**本机固定的环境性失败**（全量结果里见到它们不算回归）：路径超过 260 的图片目录选择器用例；
两条子进程按 cp1252 解码中文的用例；多显示器负原点的截图坐标用例；锁屏时的前台窗口用例（解锁后单跑即过）。

## WSL 与 `\\wsl.localhost` 共享

读 WSL 里文件的功能（用量、会话小鱼、蒸馏、配置全景）共用这几条结论：

- **访问共享会把发行版拉起来**，定时去读等于让它关不掉。先问 `wsl.exe --list --running`，只读在运行的发行版。
- **不要对 UNC 路径做 `stat` / `exists()`**：发行版没起来时会卡几秒甚至报错。在 WSL 里用 `find` 列清单，
  共享只用来读确实变长了的文件。
- **不要经共享写文件**：原子替换会把权限从 600 重置成 644。写和探测都走 `wsl.exe`。
- 目录枚举用 `os.scandir`。同一棵树，Python 约 1 秒，PowerShell 的 `Get-ChildItem` 要几十秒，后者不能当性能证据。
- 从 Git Bash 起的 Python 访问不到 `\\wsl.localhost`（报 `WinError 3`）。要读共享的探针从 PowerShell 起。
- 在 Windows 侧用 `code --remote wsl+<发行版> <路径>` 打开 WSL 目录不可靠（返回 0 却不开窗口）；
  改成在 WSL 里执行 `code .`。

## 无界面 `claude -p` 里的连接器：要登录的是 claude.ai 连接器，不是插件

症状：工作简报的 Jira 一节写「claude.ai Atlassian 连接器重连时被拒，需要重新登录；这次会话也没有加载 Atlassian 插件
MCP」；在 WSL 的交互式 Claude Code 里用 `/mcp` 重新认证了 Atlassian **插件**，再生成还是读不到。

机制（2026-11-19 在 WSL、Claude Code 2.1.329 上实测）：

- 同一个服务有两条路：claude.ai 连接器（工具名 `mcp__claude_ai_Atlassian__…`，OAuth 挂在 claude.ai 账号上）和插件
  （`mcp__plugin_atlassian_atlassian__…`，OAuth 存在本机 `~/.claude/.credentials.json`）。
- 简报走的是无界面 `claude -p`。它**只加载 claude.ai 连接器和 stdio 型服务器**：插件带的 HTTP OAuth 服务器
  （Atlassian、Slack 插件）一个都不出现——`--output-format stream-json --verbose` 的 `system/init` 事件里
  `mcp_servers` 没有它们，也没有任何报错（上游 anthropics/claude-code#36309，被 bot 关闭、未修）。交互式
  `claude mcp list` 里它们却是「✔ Connected」。所以重新认证插件对简报没有用。
- 连接器那一侧的「Needs authentication」是 claude.ai 账号层面的状态，不是本机令牌；无界面模式没有 `/mcp`，
  不会自己发起登录，模型只能在那一节写一句原因。

排查与修复：

1. 看连接器状态（`claude.ai Atlassian` 那一行）：

   ```
   wsl.exe -e bash -lc "claude mcp list"
   ```

2. 「! Needs authentication」就在 WSL 里登录这个**连接器**（浏览器里走一次 OAuth；没有浏览器的 SSH 会话加
   `--no-browser`，它会打印授权地址）：

   ```
   wsl.exe -e bash -lc 'claude mcp login "claude.ai Atlassian"'
   ```

3. 再 `claude mcp list` 确认变成「✔ Connected」，然后在简报页点「重新生成」。

要知道某次无界面运行到底挂上了哪些服务器、暴露了哪些工具，用 `--output-format stream-json --verbose` 跑一个最小提示，
读 `system/init` 事件的 `mcp_servers` 和 `tools`；不要靠让模型复述工具名。

顺带一条：Claude Code 2.1.3xx 把 `~/.claude.json` 搬到了 `~/.claude/.config.json`，两份同时存在时每次运行的 stderr
都会打一段「Two Claude Code config files exist」。按它说的把不用的那份挪开即可；配置全景的 WSL 探针读的还是
`~/.claude.json`，两份并存时它看到的是旧的那份。

## 实机验证时的注意

- 探针不要合成系统级的鼠标点击：用户正在用鼠标时会被抢走或叠成拖拽。在进程内发 Qt 鼠标事件，或用原生 API 挪窗口。
- 探针进程不是 DPI 感知的话，读到的工作区和窗口矩形是缩放后的数字，不能直接和肥鱼进程里的比。
- 后台跑着全量测试时，肥鱼日志里会出现「tick 慢帧」警告，先看当时是不是有测试在跑。
- 设置窗口是每次打开时新起的独立进程。改了设置页的代码不用重启肥鱼，但已经开着的设置窗口跑的还是旧代码。
- 并行的会话可能重启过肥鱼：截图前后核对日志文件名里的 pid 没变。
