# 配置全景

> 把这台机器上和 AI 有关的配置（肥鱼的 `config.json`、钥匙串、Windows 与 WSL 两份 `~/.claude`、两个知识库克隆、connector）
> 采成一张图，渲染成本地 HTML 地图页并用默认浏览器打开：两条账号带 × 两层，磁贴之间的线就是「谁用到谁、现在通不通」。
> 入口：右键菜单「配置全景」、岛的「模型连接」面板里的按钮、`python -m pet.panorama`。
>
> 本文写的是**现在**的只读页面。它接下来要长成能读能写的主控制台，决定见
> [ADR 0014](adr/0014-panorama-becomes-the-console.md)，步骤见[路线图](roadmap.md)；
> 下面「设计取舍」里「不起本地服务」那一条会在路线图的 M1 被推翻。

## 模块

| 文件 | 职责 |
|---|---|
| `pet/panorama/claude_home_probe.py` | 探针：只读探一个 Claude Code 家目录（账号、模型、hooks、`CLAUDE.md` 受管块、项目记忆、插件、MCP）。**只用标准库** |
| `pet/panorama/probes.py` | 探针：模型服务（`secret_tail`）、知识库克隆（`repo_info`）、`windows_side`、`wsl_side` |
| `pet/panorama/features.py` | 肥鱼的 AI 功能表 `FEATURES`，一行一项：走哪条线、生效的设置、写到哪 |
| `pet/panorama/model.py` | 图模型 `Graph`：账号带 `ZONES`、层 `TIERS`、分区、列、节点、连线、待处理；状态取值校验。没有坐标 |
| `pet/panorama/sources.py` | 来源：若干 `@source` 纯函数，把事实翻译成节点 / 连线 / 待处理；`build(facts)` |
| `pet/panorama/render.py`、`template.html` | 渲染：图 + 界面文字嵌进单个 HTML；页面脚本算版面、走线、动效、追踪、搜索 |
| `pet/panorama/service.py` | `PanoramaService`：应用里的后台两段采集 |
| `pet/panorama/__main__.py` | 命令行入口 `[--no-wsl] [--no-mcp] [--no-open]` |

## 机制与不变量

### 探针 → 来源 → 渲染

- **页面只认图的结构，对具体功能一无所知。** 加一项肥鱼功能 = `features.FEATURES` 加一行 + `panorama.feature.<id>` 两条文字；
  加一类东西 = 加一个 `@source` 函数；加一台机器或一个账号 = `model.ZONES` 多一项。页面和走线都不用动。
- 来源声明的线可以指向别的来源的节点；目标这次没出现（比如没装 WSL）时 `Graph.to_dict` 把线丢掉。
- **图上显示生效值**：功能表读设置走各功能自己的 `normalize`（如 `memory_distill.side_settings`），所以总开关关着时
  「公司侧蒸馏」显示未启用，而不是照着子开关显示成开。
- WSL 一侧和 Windows 一侧是同一份探针：`wsl_side` 把 `claude_home_probe.py` 的源码从标准输入喂给发行版里的 `python3 -`。
  所以这个文件不能 import 标准库以外的任何东西。没有 WSL（`absent`）、跑失败（`error`）、还在探（`pending`）三种分开返回。

### 图与版面

- 结构：账号带（个人 / 公司）× 层（云端 / 本机）的格子里放分区，分区里是列，节点在列里从上往下排。
- **版面和走线由页面脚本按图的结构算，哪里都不写坐标。** 连线走列之间的通道和层之间的横槽，同一束（同种线、同一个枢纽）
  共用一条车道。
- 线的画法就是状态：流动 = 通着（`live` 是这次亲自探到的，流得快）；琥珀闪 = 待处理；红线中间断开 = 坏了；灰点线 = 本机探测不到；
  很淡 = 功能没启用。节点 / 连线状态只能取 `NODE_STATES` / `EDGE_STATES` 里的值。
- 一组 connector 按状态拆成「已连」和「待处理」两块磁贴，线才能一条流动、一条琥珀。

### 只读、秘密、隐私

- **只读**：探针不写任何文件，`Config` 只加载。
- **秘密不落盘**：API key 和 GitHub token 只留「有没有 + 末 4 位」，不超过 12 个字符的连末位也不留（露 4 位就是露了三分之一）；
  凭据文件只看在不在、不读内容；仓库远端地址去掉内嵌凭据。
- **页面不联网**：单个 HTML，没有外部脚本、样式、字体。数据里的 `</` 转义，防 `</script>` 截断页面。
- 页面是自用的，**不脱敏**：里面有账号邮箱、组织名、机器名、connector 名。生成的 `%APPDATA%/big-fat-fish/panorama/panorama.html`
  不要提交或贴出去；测试样例（`tests/panorama_samples.py`）必须全是虚构的事实。

### 两段采集（`PanoramaService.open()`）

- 第一段只采 Windows 一侧（约 0.16 s）就写页面、开浏览器；第二段去 WSL 探测（约 6.7 s，几乎全是 `claude mcp list`
  逐个体检 connector）后重写。等全部采完再开，用户点完要干等 7 秒。
- 页面在 `meta.pending` 为真时每 3 秒 `location.reload()`；`render.write` 先写临时文件再替换，浏览器读不到半个文件。
  重读次数记在 `location.hash`，封顶 40 次（两分钟），肥鱼中途退出页面也不会永远刷。
- 同一次运行里再次打开：WSL 一侧先用上一轮结果垫着（`facts["refreshing"]`，也算 `pending`），新的探完再换上。
  垫底结果只在内存里（`_last_wsl`），且必须来自一轮完整跑完的结果——被作废的那一轮不留。
- **不卡界面、线程不碰活的 `Config`**：GUI 线程只做三件事——`deepcopy` 一份配置、起 daemon 线程、收 `_stage` 信号后开浏览器。
- **不点就不跑**：没有定时器、启动时工作、新设置项；服务对象第一次点时才创建，`pet.panorama` 包也是那时才 import。
- 忙时再点只把现有页面再打开一次。`aboutToQuit` → `stop()` 让 `_generation` 前进：在跑的那一轮照常写完文件，但不再开浏览器、
  不报完成。（这里每次 `open()` 也递增 `_generation`，因为有 `_busy` 保证同时只有一轮；和会话记忆蒸馏那种多任务交叠的服务不同。）

### 入口与体检结论

- 右键菜单动作 `config_panorama`（`pet/context_menus/registry.py`，默认布局 `modern-default-v1.json` 的 tools 段）；宿主有
  `on_open_config_panorama` 才显示，两种渲染拓扑都接到 `AppShell.open_config_panorama`。用户已保存的菜单布局会自动并入新动作。
- 岛的连接面板按钮（`pet/island_connections_ui.py` 的 `panorama_btn`）：单独一行（英文下并排会把面板撑宽），点了先收起面板。
- 「使用中的模型服务」那条线通不通，取[灵动岛](island.md)上 API 体检器**最近一次**的结论（`AppShell._panorama_health`），
  不是点击那一刻现查；没开岛或走命令行入口时是 `unknown`。

### 测试

- `tests/test_panorama_page.py` 用 Qt 自带的 JS 引擎（`QJSEngine`）加一个极简假 DOM **真跑页面脚本**：每个节点一块磁贴、
  每条线一条路径、坐标没有 NaN、磁贴不出界不重叠，四种 WSL 状态各跑一遍。模板里写坏一处正则整页就是空白，靠它拦。
  页面脚本用到新的 DOM / BOM 接口时要给假 DOM 补上。
- 页面文字全部来自 `pet/locale/*.json` 的 `panorama.*`；两种语言 × 四种 WSL 状态下建出来的图不许有缺的文字。

## 设计取舍

- **页面自己重读，而不是起本地服务推送**：`file://` 页面收不到推送。代价是等待期间页面上的选中状态会丢；换来没有端口、
  没有监听线程、没有安全面。
- 垫底结果不落盘：肥鱼重启后第一次打开，WSL 一侧显示「正在探测…」。
- 自动走线**不做交叉最小化**，节点明显变多后局部可能变乱。
- 菜单项放根菜单 tools 段而不是「工具与帮助」子菜单：一次右键就点得到，代价是根菜单又长一项。旧版菜单模板
  （`pet/context_menus/legacy.py`）有意没加。
- 个人账号的 connector 只能画成「探测不到」：它们挂在 claude.ai 账号上，磁盘上只有「连过哪些」，Windows 上
  `claude mcp list` 返回空。如实画成灰点线并写进待处理，不猜。

## 外部格式依赖

Claude Code 升级后先核对 `claude_home_probe.py` 读的这些：

- `~/.claude/settings.json`：`hooks`（事件 → 组 → `hooks` 列表，逐条命令计数，含 `big-fat-fish` 字样的算肥鱼的）、`model`、
  `effortLevel`、`permissions.allow`、`enabledPlugins`。
- `~/.claude.json`：`oauthAccount.emailAddress` / `organizationName`、`mcpServers`、`claudeAiMcpEverConnected`。
- `~/.claude/plugins/installed_plugins.json` 的 `plugins`；`~/.claude/.credentials.json`（只看在不在）。
- `claude mcp list` 的输出行 `名字: 地址或命令 - 状态`：按首个 `: ` 和末个 ` - ` 切（命令里可以有空格）；状态含 `Connected` = 通，
  含 `authentication` = 待授权，其余 = 坏。
- `CLAUDE.md` 受管块的起止标记与 `<!-- 更新：… -->`（由[会话记忆蒸馏](memory-distill.md)写入）。

## 排障

| 症状 | 原因 / 先查什么 |
|---|---|
| 页面整个空白 | 模板脚本有语法错误；跑 `tests/test_panorama_page.py` |
| WSL 一侧一直「正在探测…」 | 第二段没写回：看日志里「配置全景：WSL 一侧探完」；页面重读 40 次后停，手动刷新；发行版冷启动 + connector 多时会更久（上限 150 s） |
| WSL 一侧显示失败 | 探针在发行版里退出码非 0 或输出不是 JSON（那边要有 `python3`）；`python -m pet.panorama --no-mcp --no-open` 复现 |
| 模型服务的线是灰点线 | 没开岛（没有体检器）或走的命令行入口；正常 |
| hooks 的线是红色断线 | 如实反映：联动开着，但那一侧 `settings.json` 里没有肥鱼的 hook（被卸掉过），去重新安装 hooks |
| 功能明明开了却显示未启用 | 显示的是生效值：看该功能的总开关 |
| 加了探测目录后全仓库守卫变红 | `TOOL_DIRS` 或样例里的名字撞了 `test_product_copy_has_no_external_brand_reference` 禁用的词 |
