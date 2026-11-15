# PR 报告：配置全景（1/2）——把 AI 相关配置采成一张图，渲染成本地地图页面

> **基线**：`c0f3471f`（PR #43 合并后的 main）
> **分支**：`feature/config-panorama`　**日期**：2026-11-15
> **范围**：16 个文件（实现 9、文字表 2、测试 5）
> **关联**：这是「配置全景」的第一步，只有采集、建图、渲染和命令行入口；右键菜单 / 岛上的入口和后台采集在下一步（2/2）。

## 一、核心特性

和 AI 有关的设置散在很多地方：肥鱼自己的 `config.json`、钥匙串、Windows 和 WSL 两份 `~/.claude`、两个知识库克隆、
挂在 claude.ai 账号上的 connector。要回答「这项功能到底用的哪个模型、走哪个账号、写到哪个文件、现在通不通」，得一处处翻。

这一步加了一个只读的采集器和一张地图页面。`python -m pet.panorama` 采一次本机配置，写出
`%APPDATA%\big-fat-fish\panorama\panorama.html` 并用默认浏览器打开。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 一张图看全 | 两条账号带（个人 / 公司）× 两层（云端 / 本机）。磁贴是 AI 入口、功能、模型服务、账号、connector、记忆文档、配置文件、仓库；线是「谁用到谁」 |
| 2 | 线的画法就是状态 | 流动 = 通着（这次亲自探到的流得快）；琥珀闪 = 待处理；红线中间断开带叉 = 坏了；灰点线 = 本机探测不到；很淡 = 功能没启用 |
| 3 | 点一块看整条路 | 它用到的一切、会用到它的一切亮起来，其余变暗；右侧给出生效的开关 / 模型 / effort / 提示词、来源文件和键、「在 VS Code 打开」 |
| 4 | 待处理清单 | 没 key 的模型服务、待授权的 connector、联动开着但 hooks 不在、探测不到的东西；点一条定位到图上 |
| 5 | 跟界面语言走 | 页面文字全部来自 `pet/locale/zh.json` / `en.json`（各 227 条 `panorama.*`） |

**红线 / 不变量**：

- **只读**。探针不写任何文件；`Config()` 只加载（实测运行前后 `config.json` 的修改时间没变）。
- **秘密不落盘**。API key 和 GitHub token 只留「有没有 + 末 4 位」（短于 13 个字符的连末位也不留）；凭据文件只看在不在、不读内容。
  落盘的页面里因此不可能有完整的 key。
- **页面不联网**。单个 HTML，没有外部脚本、样式或字体。
- 这一步**不接进应用**：没有新线程、新定时器、新设置项，肥鱼的运行行为不变。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/panorama/__init__.py` | +10 / −0 | 包说明：探针 → 来源 → 渲染三层 |
| `pet/panorama/claude_home_probe.py` | +144 / −0 | 只读探一个 Claude Code 家目录：账号、模型、hooks（逐条命令数，哪些是肥鱼的）、CLAUDE.md 受管块、项目记忆、插件、本地 MCP、`claude mcp list`（可选）。**只用标准库**：Windows 这边 import，WSL 那边把同一份源码从标准输入喂给 `python3 -`，两边一个实现 |
| `pet/panorama/probes.py` | +118 / −0 | 模型服务列表（key 只留在不在 + 末 4 位）、知识库克隆（远端去掉内嵌凭据）、WSL 一侧（没有 WSL / 跑失败分开返回）、`windows_side` 汇总 |
| `pet/panorama/features.py` | +149 / −0 | 肥鱼的 AI 功能表，一行一项：走哪条路（个人线 / 公司线 / 只管 hooks）、生效的设置（走各功能自己的 `normalize`）、写到哪 |
| `pet/panorama/model.py` | +93 / −0 | 图模型：账号带、层、分区、列、节点、连线、待处理，状态取值校验。没有坐标 |
| `pet/panorama/sources.py` | +368 / −0 | 七个来源函数，把事实翻译成节点 / 连线 / 待处理；纯函数 |
| `pet/panorama/render.py` | +61 / −0 | 图 + 界面文字嵌进模板；`</` 转义；先写临时文件再替换 |
| `pet/panorama/template.html` | +368 / −0 | 页面：版面和走线由脚本按图的结构算（通道 + 车道），动效、追踪、搜索、线路筛选、待处理 |
| `pet/panorama/__main__.py` | +43 / −0 | `python -m pet.panorama [--no-wsl] [--no-mcp] [--no-open]` |
| `pet/locale/zh.json`、`en.json` | 各 +228 / −1 | 227 条 `panorama.*` 文字（−1 是原来最后一行补逗号） |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/panorama_samples.py` | +78 / −0 | 虚构的事实（没有一项来自真机） |
| `tests/test_panorama_sources.py` | +178 / −0 | 个人线跟着体检走；功能关了线变淡；联动开着但 hooks 没了 → 断线 + 待处理；connector 拆成通 / 待处理两块；没有 WSL / WSL 失败 / WSL 还在探测三种情况；空配置下功能表读到的是默认值；两种语言 × 四种 WSL 状态下建出来的图里没有缺的文字 |
| `tests/test_panorama_probes.py` | +137 / −0 | 临时目录里的假 Claude 家目录：hooks 计数、受管块、记忆；秘密不出现在结果里；坏 JSON / 空目录不崩；`claude mcp list` 三种行；key 末位规则；远端去凭据；WSL 通道收到的就是探针源码 |
| `tests/test_panorama_render.py` | +81 / −0 | 页面带着整张图和文字；数据里的 `</script>` 截不断页面；英文页面没有残留中文；写盘是整文件替换 |
| `tests/test_panorama_page.py` | +87 / −0 | 用 Qt 自带的 JS 引擎加一个极简假 DOM **真跑页面脚本**：每个节点一块磁贴、每条线一条路径、坐标里没有 NaN、磁贴不出界不重叠；四种 WSL 状态各跑一遍 |

### 未改动

`pet/app.py`、右键菜单、岛、设置页都没动——入口在下一步。`tests/test_architecture.py` 没有需要登记的新名单。

## 三、实现要点

- **框架而不是一张写死的图**。页面只认图的结构。加一项肥鱼功能 = `features.FEATURES` 加一行 + 两条文字；加一类东西 = 加一个
  `@source` 函数；加一台机器或一个账号 = `model.ZONES` 多一项。来源声明的线可以指向别的来源的节点，目标这次没出现
  （比如没装 WSL）时 `Graph.to_dict` 把线丢掉。
- **版面是算出来的**。分区落在「账号带 × 层」的格子里，节点在列里从上往下排。连线走列之间的通道和层之间的横槽，
  同一束（同种线、同一个枢纽）共用一条车道，所以看起来像地铁线。自动走线**不做交叉最小化**，节点多了以后局部可能变乱。
- **图上显示生效值**。功能表读设置走各功能自己的 `normalize`（`work_briefing.normalize`、`memory_distill.side_settings` …），
  所以「公司侧蒸馏」在总开关关着时显示为未启用，而不是照着 `work_distill: true` 显示成开。
- **connector 拆两块**。一组 connector 按状态拆成「已连」和「待处理」，线才能一条流动、一条琥珀 / 断开。
- **个人账号的 connector 只能标成探测不到**。它们挂在 claude.ai 账号上，磁盘上只有 `~/.claude.json` 里的「连过哪些」；
  Windows 上 `claude mcp list` 返回空。图上如实画成灰点线，待处理里写明。
- **命令行入口没有体检结论**。「模型服务通不通」是运行中的肥鱼里那个体检器的结论；命令行下使用中的服务显示为探测不到。
  下一步接进应用后从体检器取。

## 四、性能分析

**方法（可复现）**：在工作区里用真实 `%APPDATA%` 跑下面的脚本（`time.perf_counter`，各项循环次数见表）。
环境：Windows 11 Pro 26300、Python 3.13.15、PySide6 6.12.0，WSL 发行版 Ubuntu 24.04 已在运行。

```
python - <<EOF
from pet.config import Config; from pet.chat.models import SecretStore
from pet.panorama import probes, sources, render
cfg, sec = Config(), SecretStore()
probes.windows_side(cfg.data, cfg_path=cfg.path, secret_get=sec.get)   # ×5
probes.wsl_side(with_mcp=False)                                          # ×5
probes.wsl_side(with_mcp=True)                                           # ×3
sources.build(facts); render.render(graph)                               # 各 ×20
EOF
```

| 指标 | 实测 | 归属 |
|---|---|---|
| `windows_side`（读配置、钥匙串、`~/.claude`、6 次 git） | 中位 148.4 ms（146.7–207.6，n=5） | 新增，只在用户打开全景时 |
| `wsl_side`，不跑 `claude mcp list` | 中位 100.0 ms（96.7–102.9，n=5） | 新增 |
| `wsl_side`，跑 `claude mcp list`（32 个 connector 逐个体检） | 中位 6503.9 ms（6351.9–6647.4，n=3） | 新增；时间几乎全在 Claude Code 自己的体检上 |
| `sources.build`（36 个节点、40 条线） | 中位 0.4 ms（n=20） | 新增 |
| `render.render` | 中位 0.2 ms（n=20） | 新增 |
| 页面大小 | 62 334 字节 | 新增，一个文件 |
| 一次采集 + 建图 + 渲染的 Python 对象峰值（`tracemalloc`） | 794 KiB | 新增，用完即放 |

**结论**：

1. **稳态开销**：零。这一步没有接进应用，肥鱼运行时不 import 这个包，没有定时器、线程或监听。
2. **新增路径**：只有显式运行 `python -m pet.panorama` 时发生。Windows 一侧约 0.15 秒；带 connector 体检的 WSL 一侧约 6.5 秒
   （`--no-mcp` 约 0.1 秒）。下一步接进应用时这 6.5 秒必须放后台，页面先出 Windows 那半张。
3. **新的系统调用 / 磁盘 / 网络 / 线程**：每次采集 6 个 git 子进程（两个克隆各 3 条只读命令）、1 个 `wsl.exe` 子进程，都带
   `CREATE_NO_WINDOW`；写一个约 62 KB 的文件。**没有网络请求**（`claude mcp list` 的体检是 Claude Code 自己发的）。没有线程。
4. **内存**：峰值不到 1 MiB，不留缓存。

## 五、实机运行记录

本机（Windows 11，三屏；WSL Ubuntu 24.04），2026-11-15 00:45 起。账号、connector 名字这类个人 / 公司内容从略，只留形状和数量。

- **命令行跑通**：`python -m pet.panorama --no-open` →
  `…\big-fat-fish\panorama\panorama.html  (36 nodes, 40 edges, 8 quests, timing {'windows_s': 0.24, 'wsl_s': 6.67})`。
  运行前后 `config.json` 的修改时间都是 23:18:32，没有被写。
- **图上的内容与本机一致**：Windows 的 `settings.json` 9 个事件挂了肥鱼的 hook → 「会话联动 · 本机」的线是流动的；WSL 的
  `settings.json` 0 个 → 那条线是红色断线，待处理里有一条「会话联动 · WSL 开着，但那边的 settings.json 里没有肥鱼的 hook」。
  这和当天另一个排查的结论一致（WSL 的 hooks 被一轮测试卸掉了，尚未恢复）。
- **功能状态是生效值**：「公司侧蒸馏」显示为未启用（蒸馏总开关关着），不是按 `work_distill` 显示成开。
- **connector**：WSL 一侧 32 个，拆成「已连 13」和「待处理（1 失败 · 18 待授权）」两块；个人一侧 6 个只有「连过」，画成探测不到。
- **浏览器里渲染**：在应用内置的浏览器面板里打开生成的页面，脚本取到 35 块磁贴、39 条线、2 个断线标记、37 个在跑的动画
  （这一次用了 `--no-mcp`，所以少一块 connector 磁贴）；标题、图例、动效开关都是中文。
- **期间抓到并修掉的三个问题**（都有测试钉住）：
  1. hooks 计数把 `"type": "command"` 也数了进去，数量翻倍 → 改成逐条命令数；
  2. `claude mcp list` 里命令带空格的那一行解析不出来，失败的本地插件被漏掉 → 改成按首个 `: ` 和末个 ` - ` 切；
  3. 模板里一处正则被写坏，页面整个空白 → 现在有在 JS 引擎里真跑页面脚本的测试，语法错误会直接红。

**没做 / 没验证**：

- 页面在用户自己的大屏浏览器里的观感（动效会不会太花）没有由用户确认——这一步之前的原型用户看过并同意了方向。
- 英文界面只由测试覆盖（没有残留中文、文字齐全），没有在浏览器里看过英文版的排版。
- 自动走线在节点明显更多时的效果没有测。

## 测试

- `ruff check pet tests`：通过。
- 新增 4 个测试文件 + 相关守卫：`tests/test_panorama_sources.py`、`test_panorama_probes.py`、`test_panorama_render.py`、
  `test_panorama_page.py`、`test_i18n.py`、`test_architecture.py`、`test_rest_english.py`、`test_menu_english.py`、
  `test_runtime_dependencies.py`、`test_language_reload.py` → **75 passed**（offscreen，PowerShell，10.8 秒）。
- **没有跑全量**：这一步只新增一个没有任何调用方的包和两张文字表里的新键，不改现有模块、配置、生命周期或线程；
  受影响的面就是上面这些（新包自己的测试 + 文字表与架构守卫）。
