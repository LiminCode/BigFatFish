# 配置全景

> 把这台机器上和 AI 有关的配置（肥鱼的 `config.json`、钥匙串、Windows 与 WSL 两份 `~/.claude`、两个知识库克隆、connector）
> 采成一张图，画成一张地图页并用默认浏览器打开：两条账号带 × 两层，磁贴之间的线就是「谁用到谁、现在通不通」。
> 入口：右键菜单「配置全景」、岛的「模型连接」面板里的按钮、`python -m pet.panorama`。
>
> 从肥鱼里点开的页面由肥鱼进程里的**本机回环服务**提供（`http://127.0.0.1:<端口>/`），同时写一份自带数据的
> 离线快照。页面现在仍然只读；它接下来要长成能读能写的主控制台，决定见
> [ADR 0014](adr/0014-panorama-becomes-the-console.md)，步骤见[路线图](roadmap.md)。

## 模块

| 文件 | 职责 |
|---|---|
| `pet/panorama/claude_home_probe.py` | 探针：只读探一个 Claude Code 家目录（账号、模型、hooks、`CLAUDE.md` 受管块、项目记忆、插件、MCP）。**只用标准库** |
| `pet/panorama/probes.py` | 探针：模型服务（`secret_tail`）、知识库克隆（`repo_info`）、`windows_side`、`wsl_side` |
| `pet/panorama/features.py` | 肥鱼的 AI 功能表 `FEATURES`，一行一项：走哪条线、生效的设置、写到哪 |
| `pet/panorama/model.py` | 图模型 `Graph`：账号带 `ZONES`、层 `TIERS`、分区、列、节点、连线、待处理；状态取值校验。没有坐标 |
| `pet/panorama/sources.py` | 来源：若干 `@source` 纯函数，把事实翻译成节点 / 连线 / 待处理；`build(facts)` |
| `pet/panorama/page/` | 页面代码，两种交付方式共用：`shell.html`（外壳）、`app.css`，和一组原生模块——`util.js`（转义、图标、颜色）、`layout.js`（版面）、`roads.js`（走线）、`draw.js`（画）、`interact.js`（追踪、详情、搜索、筛选）、`app.js`（`start(G)` 把四步串起来）、`boot.js`（入口：数据从哪来、等新数据、连接断了） |
| `pet/panorama/render.py` | 把图变成页面要的那份数据（`page_data` / `payload`）；`shell()` / `asset()` 给本机服务；`render()` / `write()` 出离线快照 |
| `pet/panorama/service.py` | `PanoramaService`：应用里的后台两段采集与发布；持有本机服务 |
| `pet/panorama/server.py` | 本机回环服务 `PanoramaServer` + 路由表 `Router`：生命周期、守门检查、分发。**只用标准库、不碰 Qt** |
| `pet/panorama/routes.py` | `build_router`：登记有哪些网址（外壳、三个静态文件、`/api/ping`、`/api/graph`） |
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

### 页面脚本是原生模块，离线快照把它们拼起来

- 本机服务的外壳只引用入口 `boot.js`（`<script type="module">`），其余模块由浏览器按 `import` 自己装配。
- 离线快照做不到这一点（`file://` 页面加载不了模块），所以 `render.bundle()` 按 `render.MODULES` 的顺序把模块拼成
  一段普通脚本：去掉 `import` 行和 `export` 前缀，所有顶层名字落在同一个作用域里。
- 因此模块有三条写法上的约束，违反了 `bundle()` 直接报错，不会悄悄拼出坏脚本：
  只用整行的具名导入 `import {a, b} from './x.js';`；只在顶层的 `function` / `const` 前写 `export`；
  **不同模块的顶层名字不能重名**。不用默认导出、改名导入、`import *`。
- **加一个模块**：文件放进 `page/`，在 `render.MODULES` 里登记，位置在所有 import 它的模块之前。登记了才会被服务发出去
  （`ASSETS` 由它生成），也才会进快照。
- 画一张图是四步，各一个模块：`layout(G)` 算坐标并返回模型 → `roads(M)` 给每条线算折线和路径 → `draw(M, E)` 写标记 →
  `interact(M, E, map)` 接交互。模型是普通对象，后一步只读前一步的结果。

### 只读、秘密、隐私

- **只读**：探针不写任何文件，`Config` 只加载。
- **秘密不落盘**：API key 和 GitHub token 只留「有没有 + 末 4 位」，不超过 12 个字符的连末位也不留（露 4 位就是露了三分之一）；
  凭据文件只看在不在、不读内容；仓库远端地址去掉内嵌凭据。
- **页面不联网**：没有外部脚本、样式、字体；从肥鱼点开的页面只和本机服务说话（内容策略只许同源），
  离线快照是单个 HTML。快照里嵌的数据把 `</` 转义，防 `</script>` 截断页面。
- **不要令牌就能拿到的东西里没有数据**：外壳和三个静态文件只有结构、代码和界面文字；采到的一切只在 `/api/graph` 里。
- 页面是自用的，**不脱敏**：里面有账号邮箱、组织名、机器名、connector 名。生成的 `%APPDATA%/big-fat-fish/panorama/panorama.html`
  不要提交或贴出去；测试样例（`tests/panorama_samples.py`）必须全是虚构的事实。

### 两段采集（`PanoramaService.open()`）

- 第一段只采 Windows 一侧（约 0.16 s）就发布、开浏览器；第二段去 WSL 探测（约 6.7 s，几乎全是 `claude mcp list`
  逐个体检 connector）后再发布一次。等全部采完再开，用户点完要干等 7 秒。
- **发布 = 两件事**（`_publish`，在后台线程上）：先写离线快照，再把 `/api/graph` 的正文整个换成新的，`revision` 加一。
  本机服务的线程只读这一个引用，从不原地改。
- **浏览器打开的是本机服务的网址**（`_page_target`，在 GUI 线程上，第一次点才创建并启动服务）；服务起不来
  （端口绑不上之类）就退回打开快照文件。网址里 `#` 后面是令牌，日志里只记 `#` 之前的部分。
- 页面（`boot.js`）在 `meta.pending` 为真时每 3 秒问一次 `/api/graph`，`revision` 变了就整页重载；封顶 40 次（两分钟），
  肥鱼中途退出页面也不会永远问。令牌从地址栏抹掉后存在 `sessionStorage` 里，所以重载和手动刷新都还拿得到数据。
- 页面开着且看得见时每 4 分钟探活一次（`/api/ping`），所以服务的「空闲」实际是「没有看得见的页面，或 15 分钟没动」。
  探活或要数据失败时页面亮出「连接断了」，图上留着断开之前的内容。
- 离线快照自己的等待方式没变：`meta.pending` 为真时每 3 秒重读文件，次数记在 `location.hash`；`render.write`
  先写临时文件再替换，浏览器读不到半个文件。
- 同一次运行里再次打开：WSL 一侧先用上一轮结果垫着（`facts["refreshing"]`，也算 `pending`），新的探完再换上。
  垫底结果只在内存里（`_last_wsl`），且必须来自一轮完整跑完的结果——被作废的那一轮不留。
- **不卡界面、线程不碰活的 `Config`**：GUI 线程只做三件事——`deepcopy` 一份配置、起 daemon 线程、收 `_stage` 信号后开浏览器。
- **不点就不跑**：没有定时器、启动时工作、新设置项；服务对象第一次点时才创建，`pet.panorama` 包也是那时才 import。
- 忙时再点只把现有页面再打开一次。`aboutToQuit` → `stop()` 让 `_generation` 前进并停掉本机服务：在跑的那一轮照常
  写完文件，但不再开浏览器、不报完成。（这里每次 `open()` 也递增 `_generation`，因为有 `_busy` 保证同时只有一轮；和会话记忆蒸馏那种多任务交叠的服务不同。）

### 本机回环服务（`server.py`）

页面今后经它读写肥鱼。「只听本机」不是边界：浏览器里任何网页都能往回环地址发请求，而页面能改的东西里有会交给
带工具的 AI 执行的提示词。所以每个请求按固定顺序过一串检查，任何一步不过就拒，**被拒的响应也带全套加固头**：

| 顺序 | 检查 | 不过时 | 挡的是什么 |
|---|---|---|---|
| 1 | Host 正好是 `127.0.0.1:<端口>`（`localhost:<端口>` 也不行） | 421 | DNS 重绑定 |
| 2 | 方法在 `METHODS` 里；路径整条匹配路由表里的一个模板 | 405 / 404 / 400 | 预检（`OPTIONS` 一律 405）、路径穿越 |
| 3 | 带了 Origin 就必须是自己；写请求必须带 Origin | 403 | 跨站请求 |
| 4 | 浏览器标了 `Sec-Fetch-Site`：接口只认 `same-origin`，静态外壳还认 `none` | 403 | 别的站嵌入、别的站发起的调用 |
| 5 | 非公开路由要自定义请求头 `X-Panorama-Token`（常数时间比较）；放在查询串里不算 | 401 | 没拿到令牌的一切调用方 |
| 6 | 写请求：`Content-Type` 是 JSON、有 `Content-Length`、不超过 1 MiB | 415 / 411 / 413 | 跨站表单提交、超大正文 |

- **只绑 `127.0.0.1`、端口由系统随机给**；Windows 上设 `SO_EXCLUSIVEADDRUSE`，别的进程不能再绑同一个端口顶替。
- **每次启动换令牌**（`secrets.token_urlsafe(32)`）。令牌放在页面网址的 `#` 片段里交给页面（`page_url()`）：
  片段不发给服务器、不进 Referer。页面读到后应立刻从地址栏抹掉，之后只放在请求头里。
- **不发任何 `Access-Control-*` 头**；响应带只许同源的内容策略（因此页面不能有内联脚本；唯一放开的是内联 `style`
  属性，页面脚本靠它给磁贴定位——样式属性执行不了代码，外部资源又被挡着，带不走数据）、
  `Cross-Origin-Resource-Policy: same-origin`（别的源连 no-cors 的不透明响应也拿不到）、`no-store`、`nosniff`、禁止被嵌入。
- **路由表不映射文件系统**：路径只按登记的模板整条匹配；路径参数是一段、不含 `/ % \`、不以点开头。
  公开路由（`Router.static`）只放不含用户数据的外壳、脚本、样式，数据一律走要令牌的接口。
- **空闲自停**：`IDLE_SECONDS`（15 分钟）没有一次**放行的**请求就停。被拒的请求不算数——坏页面一直敲门不能让服务一直开着。
  停了再启动是新端口、新令牌，旧标签页作废。
- **`stop()` 不等轮询**：服务线程睡在「等下一个连接」里，`stop()` 敲一下门把它叫醒。退出应用时它在 GUI 线程上。
- **处理函数的异常不外泄**：页面只拿到 `{"error": "internal_error"}`，细节进日志。日志只记请求行和状态码，不记请求头。
- `on_stop` 回调在服务线程或调用 `stop()` 的线程上，里面不能碰 Qt 对象，要通知界面就发信号。

### 入口与体检结论

- 右键菜单动作 `config_panorama`（`pet/context_menus/registry.py`，默认布局 `modern-default-v1.json` 的 tools 段）；宿主有
  `on_open_config_panorama` 才显示，两种渲染拓扑都接到 `AppShell.open_config_panorama`。用户已保存的菜单布局会自动并入新动作。
- 岛的连接面板按钮（`pet/island_connections_ui.py` 的 `panorama_btn`）：单独一行（英文下并排会把面板撑宽），点了先收起面板。
- 「使用中的模型服务」那条线通不通，取[灵动岛](island.md)上 API 体检器**最近一次**的结论（`AppShell._panorama_health`），
  不是点击那一刻现查；没开岛或走命令行入口时是 `unknown`。

### 测试

- `tests/test_panorama_page.py` 用 Qt 自带的 JS 引擎（`QJSEngine`）加一个极简假 DOM **真跑页面脚本**：每个节点一块磁贴、
  每条线一条路径、坐标没有 NaN、磁贴不出界不重叠，四种 WSL 状态各跑一遍。脚本里写坏一处正则整页就是空白，靠它拦。
  页面脚本用到新的 DOM / BOM 接口时要给假 DOM 补上。`boot.js` 也在这里跑：假 `fetch` 同步返回、假定时器由测试触发，
  所以 `boot.js` 只用 `.then`，不用 `async` / `await`。同一个文件里还有一条用例让 JS 引擎按真正的模块规则加载 `app.js`
  （`importModule`），并要求它和拼出来的脚本画出同一张图：哪个模块导入了别人没导出的名字，或者两条交付路径分了叉，都在这里红。
- `tests/test_panorama_render.py` 守两条：离线快照不向任何地方要东西；外壳和静态文件里没有采到的数据、没有内联脚本。
- 页面文字全部来自 `pet/locale/*.json` 的 `panorama.*`；两种语言 × 四种 WSL 状态下建出来的图不许有缺的文字。
- `tests/test_panorama_server.py` 用真实的回环套接字测服务：`http.client` 能随意改 Host / Origin，正好冒充浏览器里的坏页面。
  上表每一行至少一条用例；空闲自停靠注入的假时钟推进后等事件，不用固定 sleep。往路由表加接口不用重测守门，
  但**改 `_check` 的顺序或条件必须先改这里的拒绝矩阵**。

## 设计取舍

- **起本机服务，而不是只写文件**（推翻了第一期的取舍，见 [ADR 0014](adr/0014-panorama-becomes-the-console.md)）：
  `file://` 页面不能回传，改不了任何东西。代价是多一个只在用的时候开着的回环端口，和上面那一串守门检查。
- **一份页面代码、两种交付**：离线快照把外壳、样式、脚本和数据内联成一个文件，本机服务把它们分开发。
  不维护两套页面；`boot.js` 靠有没有嵌入的数据分辨自己在哪一种里。
- **等新数据时整页重载，而不是原地重画**：`start()` 只在载入时跑一次，监听只挂一次。代价是等待期间页面上的选中状态会丢；
  路线图 M1 的「事件推送」那一步再改。
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
| 页面整个空白 | 页面脚本有语法错误（跑 `tests/test_panorama_page.py`）；或者有内联脚本 / `on*` 属性被内容策略挡了（看浏览器控制台） |
| 从肥鱼点开是空白、离线快照却正常 | 某个模块没在 `render.MODULES` 里登记（服务发不出去，浏览器控制台有 404），或 import 的名字对不上 |
| 生成页面时报 `uses an import/export form the bundler does not handle` | 模块里用了拼不了的写法（默认导出、改名、`import *`、跨行）；改回整行具名导入 |
| 磁贴全挤在左上角 | 内联 `style` 属性被挡了：内容策略里的 `style-src-attr 'unsafe-inline'` 被改掉了 |
| 页面顶上红条「连接断了」 | 肥鱼退出了，或服务空闲自停了（页面藏着超过 15 分钟）；从肥鱼里再点一次「配置全景」 |
| 点了之后打开的是 `file://` 的页面 | 本机服务没起来，退回了离线快照；看日志里「本机服务起不来」后面的异常 |
| WSL 一侧一直「正在探测…」 | 第二段没发布：看日志里「配置全景：WSL 一侧探完」；页面问 40 次后停，手动刷新；发行版冷启动 + connector 多时会更久（上限 150 s） |
| WSL 一侧显示失败 | 探针在发行版里退出码非 0 或输出不是 JSON（那边要有 `python3`）；`python -m pet.panorama --no-mcp --no-open` 复现 |
| 模型服务的线是灰点线 | 没开岛（没有体检器）或走的命令行入口；正常 |
| hooks 的线是红色断线 | 如实反映：联动开着，但那一侧 `settings.json` 里没有肥鱼的 hook（被卸掉过），去重新安装 hooks |
| 功能明明开了却显示未启用 | 显示的是生效值：看该功能的总开关 |
| 页面调接口得到 421 | Host 不是 `127.0.0.1:<端口>`：用 `localhost` 打开的，或者经过了代理 / 端口转发。只能用 `page_url()` 给的网址 |
| 页面调接口得到 401 | 令牌不对：服务空闲自停后重启过（新令牌），这个标签页是旧的；重新点一次「配置全景」 |
| 页面调接口得到 403 | 请求不是页面自己发的（Origin 或 `Sec-Fetch-Site` 不对），或写请求没带 Origin（非浏览器的调用方要自己带上） |
| 加了探测目录后全仓库守卫变红 | `TOOL_DIRS` 或样例里的名字撞了 `test_product_copy_has_no_external_brand_reference` 禁用的词 |
