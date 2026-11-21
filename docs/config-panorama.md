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
| `pet/panorama/storage_probe.py` | 存储探针：把数据目录和个人 Claude Code 家目录走一遍，每个文件归到[存储表](config-and-data.md)的哪一项；配置备份此刻的状态。只看文件名、大小、修改时间 |
| `pet/panorama/store_walk.py` | 走目录、按存储表数文件的那段代码（`survey_tree`）。**只用标准库、不 import 肥鱼的模块**：这台机器上和 WSL 里跑的是同一段 |
| `pet/panorama/wsl_file_agent.py` | 在 WSL 里替页面列文件、读文件的那一小段（`agent_main`）。**只用标准库**，由 `files.Reader` 喂给发行版里的 `python3 -` |
| `pet/panorama/features.py` | 肥鱼的 AI 功能表 `FEATURES`，一行一项：走哪条线、生效的设置、写到哪 |
| `pet/panorama/memory_scope.py` | 记忆按作用域：`analyse` 把两台机器的记忆索引摊平比对，给每条标上 `dup` / `to_global` / `in_global` / `both_sides`。纯函数 |
| `pet/panorama/places.py` | 存储画在图上哪里：`PLACES`（一个地方 = 几个根 + 分区 + 列 + 谁往这里写）、`OWN_TILE`、`ALSO_ON` |
| `pet/panorama/model.py` | 图模型 `Graph`：账号带 `ZONES`、层 `TIERS`、分区、列、节点、连线、待处理；状态取值校验。没有坐标 |
| `pet/panorama/sources.py` | 来源：若干 `@source` 纯函数，把事实翻译成节点 / 连线 / 待处理；`build(facts)` |
| `pet/panorama/page/` | 页面代码，两种交付方式共用：`shell.html`（外壳）、`app.css`，和一组原生模块——`util.js`（转义、图标、颜色）、`layout.js`（版面）、`roads.js`（走线）、`draw.js`（画）、`viewer.js`（文件查看面板）、`memory.js`（记忆一览面板）、`form.js`（设置表单）、`settings.js`（设置面板：开、关、跨重画存活）、`repair.js`（待处理里的「修复」）、`interact.js`（追踪、详情、搜索、筛选）、`app.js`（`start(G)` 把四步串起来）、`client.js`（取令牌、带令牌的 fetch，两张页共用）、`boot.js`（入口：数据从哪来、等新数据、连接断了）；报告页自己的 `report.html` / `report.css` / `report.js` |
| `pet/panorama/render.py` | 把图变成页面要的那份数据（`page_data` / `payload`）；`shell()` / `asset()` 给本机服务；`render()` / `write()` 出离线快照 |
| `pet/panorama/service.py` | `PanoramaService`：应用里的后台两段采集与发布；持有本机服务 |
| `pet/panorama/server.py` | 本机回环服务 `PanoramaServer` + 路由表 `Router`：生命周期、守门检查、分发。**只用标准库、不碰 Qt** |
| `pet/panorama/feed.py` | 发布台 `Feed`：存最近一次发布的数据和它的编号，让「等新数据」的请求等到有为止。**只用标准库** |
| `pet/panorama/routes.py` | `build_router`：登记有哪些网址（外壳、静态文件、`/api/ping`、`/api/graph` 及它的「等更新的」用法、`/api/files`、`/api/file`、`/api/settings/<组>`、`/api/audit`、`/api/actions/<动作>`、`/report/<名字>` + `/api/report/<名字>`） |
| `pet/panorama/actions.py` | 页面动作的处理器：`repair_hooks`（装 hooks）、`generate_report`（报告页的「重新生成」） |
| `pet/panorama/reports.py` | 报告页的数据：`work_briefing` / `personal_briefing(service_of, config)` 把各自服务的最近一份翻成页面要摆的字典；`split_sections`、`trace_sections` / `personal_details`、`generate_briefing`、`open_inspiration` |
| `pet/panorama/notes.py` | 笔记页的数据与动作：`work_notes(service_of, config)` / `slack_watch(notes_of, watch_of, config)` 把 `WorkNotesService`（和 Slack 关注的检查状态）翻成页面字典（provider 带 `page = "notes"`）；`note_action` 把页面的 `add / done / snooze / delete / resummarize / open_link / obsidian / folder / push` 分发到服务；`check_slack` 是 Slack 页「现在检查」的分发项 |
| `pet/panorama/markdown.py` | 简报那一小块 Markdown → HTML（零依赖，只认简报会写出来的子集；★ / bug 记号变成类名） |
| `pet/panorama/settings_api.py` | 读、改一组设置的那段逻辑（`read` / `write`）：先重读、对版本、校验、落盘、记审计。不碰 Qt，拿活的 `Config` 干活 |
| `pet/panorama/files.py` | 文件查看的那道门：`VIEWABLE` 名单、`Reader.listing` / `Reader.read`。**只用标准库、不碰 Qt** |
| `pet/panorama/__main__.py` | 命令行入口 `[--no-wsl] [--no-mcp] [--no-open]` |

## 机制与不变量

### 探针 → 来源 → 渲染

- **页面只认图的结构，对具体功能一无所知。** 加一项肥鱼功能 = `features.FEATURES` 加一行 + `panorama.feature.<id>` 两条文字；
  加一类东西 = 加一个 `@source` 函数；加一台机器或一个账号 = `model.ZONES` 多一项。页面和走线都不用动。
- 来源声明的线可以指向别的来源的节点；目标这次没出现（比如没装 WSL）时 `Graph.to_dict` 把线丢掉。
- **图上显示生效值**：功能表读设置走各功能自己的 `normalize`（如 `memory_distill.side_settings`），所以总开关关着时
  「公司侧蒸馏」显示未启用，而不是照着子开关显示成开。
- WSL 一侧和 Windows 一侧是同一份探针：`wsl_side` 把一份源码从标准输入喂给发行版里的 `python3 -`。这份源码
  （`probes.wsl_source()`）是三个文件按顺序拼成的：存储表 `data_stores.py`、走目录的 `store_walk.py`、家目录探针
  `claude_home_probe.py`。探针的入口看到另外两样在同一个作用域里，就顺手把 `~/.claude` 走一遍，按存储表数出每一项
  （结果里的 `storage`）。所以**这三个文件都不能 import 标准库以外的东西，也不能定义同名的顶层名字**（拼在一起后一个会
  悄悄顶掉另一个）——`tests/test_panorama_wsl_side.py` 两条都查，并且把拼出来的源码用本机 Python 在假家目录上原样跑一遍。没有 WSL（`absent`）、跑失败（`error`）、还在探（`pending`）三种分开返回。

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
  `interact(M, E, map, kept)` 接交互。模型是普通对象，后一步只读前一步的结果。
- **`start(G, kept)` 可以反复调**（数据换了页面原地重画）。它返回一个 view：`capture()` 记下用户正看着什么
  （选中的节点、线路筛选、搜索词），`dispose()` 把这一次挂的监听一次摘干净（所有监听带同一个中止信号）。
  重画的顺序固定：`kept = view.capture()` → `view.dispose()` → `view = start(新数据, kept)`。
  往 `interact` 里加监听必须带上那个信号（第三个参数 `on`），否则重画一次就多一套。

### 页面上的两套颜色

- **地图自己的配色**（`app.css` 开头那组变量、磁贴、分区、线）只属于这张图，只有深色一套。
- **控件的颜色**（搜索框、按钮，以及以后的表单）用 `--m-*` 变量，来自和 Qt 设置窗口共用的令牌表
  `pet/theme_tokens.py::METRO_TOKENS`。`tokens_css()` 把它生成成 `tokens.css`：本机服务当静态文件发（排在 `app.css` 前面），
  离线快照内联进去。网页样式里**控件不写死颜色**，测试守着这一条，也守着 `var(--m-…)` 引用的名字表里都有。
- 令牌表有明暗两张，`tokens.css` 里两张都在（浅色挂在 `:root[data-theme="light"]` 下）。现在没有页面启用浅色：
  地图的配色还没有浅色版本，只换控件会一半明一半暗。

### 存储：设计来自存储表，此刻的情况来自探针

存储表（`pet/data_stores.py`）有几十项，一项一块磁贴图就没法看了。所以：

- **按地方归拢，再按「硬盘没了会怎样」分块。** 一个地方（`places.PLACES`）是一个或几个根：肥鱼的（数据目录 + 钥匙串 +
  系统登记项）、个人 Claude Code 的（`~/.claude` + `~/.claude.json`）、WSL 里公司 Claude Code 的。每个地方最多三块磁贴，
  对应 `data_stores.STANDINGS`：**有备份机制**（`kept`）、**只在这台机器**（`local`，琥珀色，进待处理）、**丢了不要紧**（`free`，小一号）。
  点开是里面的每一项：叫什么、里面是什么、在哪、谁在写、丢了从哪恢复——这几句来自字表的 `stores.<键>.*`。
- **存储线**从写它的入口（肥鱼、Claude Code）连到这几块磁贴；「有备份机制」那块再连到 GitHub。
- **设计和现状分开说。** 存储表说 `config.json` 有机制备份；探针（`storage_probe.backup_state`）看配置备份此刻开没开、
  上次什么时候、上次成没成，磁贴的状态和去 GitHub 那条线跟着它走：没开 = 琥珀 + 线很淡，上次失败 = 线断开，
  开着还没备份过 = 探测不到，暂停 = 琥珀。没开、失败、暂停各有一条待处理。
- **这台机器上没有的不算缺口。** 探针数出每一项此刻有多少文件；一项也没有的存储在清单里垫底、显示成未启用，
  不计入「N 种只在这台机器上」。WSL 一侧由那边的探针自己数（同一段 `store_walk.survey_tree`），所以也有数目、
  也报不认得的文件；只有垫着的是老探针的结果（没有 `storage` 这一段）时，才只按存储表列出、不说有没有。
- **表不认得的文件**单独一块磁贴（`没登记的文件`）加一条待处理：只报名字，最多 30 个，总数照实报。
  这是存储表守卫的兜底——守卫只看源码里的文件名字面量，漏掉的在真机上露出来。
- 图上本来就有磁贴的存储（两个知识库克隆 `OWN_TILE`；`CLAUDE.md`、项目记忆、`settings.json`、插件 `ALSO_ON`）
  在那块磁贴上补一行「丢了从哪恢复」。知识库克隆另外显示**没推送的提交**（有 = 琥珀 + 待处理）和**没提交的改动**（有 = 一条提示）：
  按本地记得的上游算，不联网。
- 探针**不打开任何文件**（配置备份的簿记除外）；不跟符号链接和目录联接进去；一个目录最多数 50,000 个文件，
  数不完会说（`quest.truncated`）。用户的家目录不走，只看表里点了名的文件（`storage_probe.named`）。

**存储表里加了一个新的根**：在 `places.PLACES` 里说它画在哪，否则 `tests/test_panorama_storage.py` 会红。

### 连接器详情

点一块连接器磁贴，清单里每一条下面跟着几行：**连到哪**（地址或命令行）、**类型**（远程服务 / 本地命令）、**上次探测**。

- 三种来源，能知道的多少不一样，图上如实分开：
  - `claude mcp list` 的实时结果（现在只在 WSL 一侧跑）：每条有状态、连到哪、探测时间（`mcp_probed_at`）。
    claude.ai 账号上的连接器、插件带的、自己登记的都在这一份里。
  - `~/.claude.json` 里登记的 MCP 服务器（`claude_home_probe.mcp_detail`）：用户级的和项目级的（`projects.<路径>.mcpServers`），
    每条有类型（`type`）、地址或命令行、环境变量和请求头的**名字**。这是配置，不是体检：它不说通不通。
    WSL 一侧一直有这块磁贴（「本地 MCP」）；这台机器上登记了才多一块 `mcp_win`。
  - 个人账号在 claude.ai 上的连接器：本机只读得到「连过哪些」，没有地址、没有状态、也没有探测时间，所以这些行下面什么都不跟。
- **「上次探测」是那份数据真正的年龄**：两个 Claude Code 入口磁贴上各有一行。重新打开页面时 WSL 那一半先垫着上一轮的结果，
  这时写的是上一轮的时间，后面带「（正在重新探测…）」，新的到了再换。
- **地址和命令行里的密钥不带出来**（探针里就换掉，进不了图和快照）：地址去掉 `账号:口令@` 和查询串（原来有查询串就留一个 `?…`）；
  命令行里名字像密钥的参数（`--token X`、`--api-key=X`、`TOKEN=X`）把值换成 `***`。认的是**参数名字**像不像，不是值，
  所以直接把密钥当位置参数写在命令行里的认不出来。要看原文，点「查看」开 `~/.claude.json`（那条路不脱敏）。

**详情栏的列表怎么摆**（2026-11-20，对所有带条目的磁贴一样，连接器只是条目最多的那块）：

- **默认紧凑**：每条一行（状态点 · 名字 · 右侧一句）；带说明的条目行首是 ▸，点了展开那一条的 `dl.more`（再点收起）。
  展开状态按「磁贴 id + 条目名」记在 `interact.js` 的模块变量里，数据更新重画后还在。列表头上一行工具：条数、
  「全部展开 / 全部收起」（存 `localStorage`，只是这个浏览器的便利）。
- **列表内筛选**：超过 5 条时多一个输入框，按名字 / 右侧一句 / 说明里的值过滤（`util.rowMatches`，不分大小写），只改每条的
  `hidden`、不重画（重画会丢输入焦点）；筛选词按磁贴记住。页顶的搜索框照旧只高亮磁贴。
- **相对时间**：事实和说明里长得像 `YYYY-MM-DD HH:MM(:SS)` 的值，后面补「· N 分钟 / 小时 / 天前」（`util.ago`，不到 1 分钟是
  「刚刚」，未来时间不补），按画的那一刻算——数据更新会重画，所以不另起定时器。
- **右栏能拖宽**：两列之间有一条把手（`#gutter`），拖动改 CSS 变量 `--aside-w`（`util.clampAside`：300–720px，默认 380），松手存
  `localStorage`，双击复原；地图随之 `fit()` 重算缩放。窄于 1280px 的单栏版面把手藏起。离线快照同一套外壳，也能用。

### 工作空间（「项目与会话」磁贴）

两个 Claude Code 各有一块：它在哪些项目目录里干过活、各有多少次会话、上次什么时候。

- 数据由家目录探针带回来（`claude_home_probe.workspaces`）：`~/.claude/projects/` 下每个**有会话记录或有记忆**的目录一条，
  最近用过的在前，最多列 60 个（总数照实报）。既没有会话也没有记忆的目录只数个数。
- **真实路径不猜。** 目录名是绝对路径编码出来的（不是字母数字的字符全换成 `-`），反过来解不回去。所以：先拿 `~/.claude.json`
  里登记的项目路径编码后去对目录名；没登记的，看最新一份会话记录开头的工作目录，**编码后正好等于目录名才用**
  （会话中途换过目录的对不上）；都不行就写「不知道」，灰点。
- **目录还在不在**：路径知道、目录已经删掉的显示成未启用（变淡、垫底），并合成一条提示——它的会话记录和记忆还占着地方。
  路径是另一个系统的写法（在 WSL 里看到 `C:\…`）答不了，也是灰点。
- 每条下面：路径、会话原文多少次多大、记忆几条、上一次会话的几个数（时长、花费、增删行数——来自 `~/.claude.json`
  里那个项目的 `lastDuration` / `lastCost` / `lastLinesAdded` / `lastLinesRemoved`，没登记的项目没有）。
- **只读文件名、大小、时间**，外加会话记录开头的那一个 `cwd` 字段。会话里说了什么不读、不带。没有会话标题：
  那要读会话内容，这一步不做。
- 空的项目目录攒到 20 个以上单独提一句（自动化跑出来的一次性目录会留下很多）。

### 记忆按作用域（「记忆一览」）

页面右上角的「记忆一览」，和 `CLAUDE.md`、项目记忆这四块磁贴详情里的同名按钮，打开一张面板：每台机器一栏，
栏里先是全局，再是各个项目。

- **作用域是记忆放在哪决定的**，三层：机器（这台 Windows 上个人的、WSL 里公司的）→ 全局（那个家目录的 `CLAUDE.md`，
  受管块里每条规矩算一条；受管块之外你自己写的只列小标题）→ 项目（`projects/<项目>/memory/` 里每个文件，`MEMORY.md` 是目录不算）。
- **数据由家目录探针顺手带回来**（`claude_home_probe.memory_index`）：每个记忆文件只读开头 4 KB，取文件头里的
  `name` / `description` / `type`，没有文件头就取第一个标题或文件名。**只带名字和说明，不带正文**；说明和规矩正文截到 240 字，
  最多 600 条。两边是同一份探针，所以 WSL 一侧也有。
- **标记只按字面判**（`memory_scope.analyse`）：标题一样（不分大小写、不看标点和空白），或者说明一样（归一化后不足 12 个字的不比）。
  换了个说法的同一件事判不出来——那要模型去读，这里只做便宜、确定、不会冤枉人的那一半。
  - `重复`：同一台机器上还有一条一样的；
  - `像是全局的`：同一条出现在这台机器的两个以上项目里（同一个仓库的几个工作区各带一份记忆时会大量出现）；
  - `全局里已有`：这台机器的全局规矩里已经有了，项目里这份多余；
  - `两边都有`：另一台机器上也有。**不算放错**，个人和公司各需要一份，只是告诉你。
- 后两种「放错作用域」加上重复，每台机器合成一条提示（`info`，不是要处理）挂在项目记忆磁贴上。
- 面板不向服务要东西，数据就在图里（`G.memory`，文字由 `sources.memory_view` 配好）。条目带「查看」，
  点了直接在文件查看面板里翻到那个文件（WSL 一侧的经 `wsl.exe` 读）；离线快照里没有。Esc 一次只关最上面那一层。
- 这一步**只看不改**：不能在页面上合并、移动或删除记忆。

### 改设置：写入链路

本机服务第一批**会改东西**的接口：`GET /api/settings/<组>`（值、版本、每一项怎么画）、`PATCH /api/settings/<组>`、
`GET /api/audit`。页面上的入口见下面「改设置：页面上的入口」；审计记录还没有地方翻（路线图 M3 最后一项）。

```mermaid
sequenceDiagram
    participant P as 页面
    participant H as 本机服务（请求线程）
    participant G as 主进程界面线程
    participant D as config.json
    P->>H: PATCH {base: 版本, changes: {项: 值}}
    Note over H: 守门（server.py）：Host → 来源 → Sec-Fetch-Site → 令牌 → JSON、不超过 1 MiB
    H->>G: on_gui：排一个队列信号，请求线程等结果
    G->>D: reload()
    Note over G: 版本 → 可用 → 逐项校验（check_changes）
    G->>D: set + save()
    Note over G: 记审计 → 应用链 → 重新发布功能磁贴
    G-->>H: 新版本和新值，或者拒绝的原因
    H-->>P: 200 / 400 / 404 / 409 / 422 / 500 / 503
```

- **只有界面线程碰 `Config`。** 请求线程经 `PanoramaService.on_gui` 把活儿排过去再等（最多 10 秒）。等不到、而那边还没开始，
  这次调用就**作废**并回 503 `busy`——界面线程之后轮到它也不会再跑，不然页面以为没改成、过一会儿设置却自己变了。
  已经开始跑了就接着等它跑完。
- **先 `reload()` 再写。** 设置窗口是另一个进程，两边都整份写配置。它刚存过别的键、主进程内存里还是旧的时候，
  不重读就写回去会把它的改动盖掉。
- **版本是这一组生效值的指纹**（`settings_table.version`），页面读的时候拿到、写的时候交回来。对不上回 409 `stale`
  并附上现在的值。它不是计数器：值改过又改回去，原来的版本号就又有效了——页面看到的值和现在一样，没有东西会被盖掉。
- **提交的值被功能自己的校验改掉了，就拒**（422 `invalid`，指出是哪几项）。`normalize` 遇到不合法的值不报错，而是悄悄换成
  默认值；读配置时这是对的，写的时候会让用户以为存上了。`check_changes` 把改动合进去过一遍 `normalize` 再逐项比，
  不一样就是被改掉了。文本只容许去掉首尾空白这一种差别；连「9」被规范成「09:00」也算不一样。模型名、effort 会拼进
  shell 命令，这一步等于复用了它们已有的白名单。
- **一次请求要么全存、要么全不存**；只能逐项改，不能整块换掉一层字典；表里没有的项一律拒。存不上（`save()` 失败）
  就把内存里的值退回去，回 500 `save_failed`。
- **审计**（`pet/settings_audit.py`）：每改一项记一行到数据目录的 `settings-audit.jsonl`——时间、组、项、旧值、新值、来源，
  最多 500 行。旧值新值记原文（提示词也记），单个值超过 8192 个字符截断。它只留在本机（存储表里是 `mixed` / `disposable`）。
  审计写不进去只进日志，不让已经存好的设置回滚。
- **改完之后**：调应用链（应用构造服务时传进来的 `_apply_external_config_change`，和设置进程存盘后主进程走的是同一条；
  它出错不影响已经存好的设置），再拿上一次发布用的事实把「功能」那一段按新配置重读、发布一次，开着的页面原地更新。
  有一轮采集正在路上时，它是拿旧设置开的头，回来时按新设置再盖一次。
- 日志里只记改了哪一组的哪几项，**不记值**。

**页面这一侧的表单**是 `page/form.js` 的 `settingsForm(host, S, send, on)`：`show(描述)` 按 `GET /api/settings/<组>` 的回答画，
页面里没有任何一项设置的名字。

- 八种控件：开关（`role="switch"` 的复选框）、下拉、可自填的下拉（值不在可选值里就自动打开自填框）、数字、单行文本、长文本、
  一行一个的列表（`lines`：值是字符串列表，框里一行一项；存的时候每行去掉首尾空白、空行不要，打回原样不算改过）、
  记录表（`records`：值是字典的列表，描述里的 `fields` 是列；一行一条，「加一行」「×」删行，整张表一个「保存」；草稿是一组对象，
  第一次改时从当前值复制；存的时候每个字段去首尾空白、全空的行不要，和服务那边 `_as_stored` 一样，打回原样不算改过）。
  下拉的可选值可以是整数（详情卡文字大小 85 / 100 / 115 / 130）：`<option>` 的值只能是字串，提交时按 `choices` 换回声明的那个值，
  服务那边按类型校验（字串 `"115"` 是 `not_a_choice`）。
  收在「高级」里的折起来，标出有几项。每个控件都有 `<label for>` 指着它；状态行是 `role="status"`。
- 数字可以带上下限和单位（设置表里的 `Setting.bounds` / `unit`，描述里的 `min` / `max` / `unit`）：输入框带 `min` / `max`，整数范围再带 `step="1"`，
  后面跟着单位。超出范围或该是整数却带小数的，页面自己就不交，那一行写明能填多少到多少；服务那边同样按 `bounds` 拒（`out_of_range`）。
- 下拉的选项可以带显示文字（`Setting.labels`，描述里和 `choices` 一一对应的 `labels`，空串 = 照原样显示值）：写了文字的显示「文字 · 值」，
  值是空串时只显示文字。个人助理的模型和 effort 存空串表示「跟 AI 对话一致」，就靠它写出来。
- 一个配置键可以分成几组（会话记忆蒸馏的个人侧 / 公司侧）：每组把另一组的键写进 `not_editable`，磁贴用 `Feature.settings_group`
  指明是哪一组（不写就按 `config_key` 找）。
  不声明就会落到功能的 `normalize` 上——它把 3 悄悄夹成 5，用户以为存上了 3。
- **什么时候交**按描述里的 `commit`：开关、下拉、数字一动就交；文本和列表等用户点「保存」，改了没存的那一行左边一条琥珀色，可以「撤销」。
  打字时不整张重画（只换那一行的按钮），所以光标不会丢。
- 长文本有 `builtin`（内置文字）时：值为空就把内置文字放进框里，旁边说「正在用内置的」；存的时候文字和内置的一样就存空，
  「恢复内置」把框里换回内置文字。和 Qt 设置窗口的提示词编辑器同一个规矩。
- 服务的每一种回答：200 换成新值、说「已保存」；409 `stale` 换成回答里带的现在的值；422 在那几项下面标红，值回到存着的；
  503、409 `unavailable`、500、连不上各一句话。**没存上的文字任何时候都不丢**，只有存上了才清掉。
- 交出去之后、回答到之前，所有控件变灰，再点也不会发第二次；点下去的那个值先显示着（开关不会先弹回去）。
- 依赖开关（`depends_on`）关着时，那一项变灰。这一组在这台机器上用不了（`available` 是假）时，整张表单变灰，顶上说为什么。
- 样式在 `app.css` 的 `.sform`，控件颜色一律用 `--m-*` 令牌；尊重系统的「减少动效」。

### 改设置：页面上的入口

已搬过来的组（2026-11-19）：工作简报、Slack 关注、工作笔记、个人助理、会话记忆蒸馏（两组），以及 `agent_link` 一个配置键分成的四组——
本机联动 `link_win`、WSL 联动 `link_wsl`（公司带）、会话小鱼 `session_fish`、最近的对话 `session_history`。
搬一组，设置窗口里那一组的控件和保存代码同时删掉，原处留一行说明和一个按钮（ADR 0014：任何时刻一项设置只有一个编辑入口）。

`agent_link` 那四组在设置窗口里本来就没有控件（只有提示音效，仍留在「互动」里，M7 再搬），删的是**右键菜单里的选值子菜单**：
开关留在菜单（通道、每个会话一只小鱼、记录最近的对话），上限 / 保留天数 / 配色 / 字号 / 桂冠 / 行数换成一条「会话小鱼设置…」
（`SpriteMenuFacade.open_session_fish_settings` → `open_config_panorama(focus="session_fish")`，会话小鱼自己的菜单同一条）。
页面改完的生效链：`_apply_external_config_change` → 各窗 `refresh_pet_settings` → `AgentLinkManager.apply_config` 启停监视器
（**从不写 hooks**，ADR 0006；hooked 通道「在跑 → 停」时顺带卸掉肥鱼自己装的 hooks，和菜单关闭一样）；
`OverlayShell.refresh_settings` → `_sync_session_settings`：关掉开关在场的会话小鱼离场、核对一次名册（保留天数）、换桂冠、
岛上列表重取，「最近的对话」的保留天数 / 条数真变了才重扫一遍 transcript。

### 动作：待处理里的「修复」

页面上第一个**不是改设置、而是请主进程做一件事**的入口（2026-11-19）：联动开着、那一侧的 `settings.json` 里却没有肥鱼的 hooks 时，
待处理里那一条和 `settings.json` 磁贴的详情各出一个「修复」按钮。

```mermaid
sequenceDiagram
    participant P as 页面（repair.js）
    participant H as 本机服务
    participant G as 主进程界面线程
    participant F as ~/.claude/settings.json
    P->>P: confirm()：同意文案（同右键菜单那条路的 Qt 弹框）；取消什么都不发
    P->>H: POST /api/actions/repair_hooks {agent: claude | claude_wsl}
    H->>G: on_gui（和改设置同一条路）
    G->>F: AgentLinkManager.install_hooks_consented(agent)
    Note over G: 本机当场写 → installed；WSL 后台起 wsl.exe → pending，装完发 install_finished
    G-->>P: {state: installed | pending | failed}
    G->>G: 装好的那一侧重探一次（PanoramaService.refresh(side)），发布，页面原地重画，那条线变回来
```

- **动作是独立的 POST，不藏在 PATCH 设置里**：打开通道的开关永远只是起监视器，装 hooks 永远是另一次明确的点击（ADR 0006 的决定不变，
  只是同意框从桌面搬到了用户正看着的页面；ADR 末尾有补记）。服务端拿到请求就视为「用户点了是」，只调管理器的「装」那一半
  （`install_hooks_consented`），不再弹 Qt 的问题框；菜单那条路仍是 `set_enabled` 先问再调同一个「装」。
- **登记**：`actions.py` 里一个处理器 `handler(body) -> dict`，应用构造 `PanoramaService` 时传 `actions={"repair_hooks": ...}`；
  路由 `POST /api/actions/<名字>` 把它转到界面线程。处理器自己校验参数（只认两条 hooked 通道，400 `bad_agent`；没有管理器 503
  `no_manager`），不认识的名字 404，处理器出错 500 `action_failed`。以后「重新测试连接」走同一个口。
- **装完重探**：`_republish` 只重读功能、不重探，而 hooks 在不在是探针读文件得来的。`PanoramaService.refresh(side)` 只重探一侧
  （`win` 重跑 Windows 探针、接上上一次的 WSL 结果；`wsl` 只换那一半），在后台线程里，不开浏览器；一轮完整采集正在路上就不另起。
  WSL 那条装完由 `install_finished` 信号触发重探（处理器对同一个管理器只接一次）。
- **页面**：`repair.js` 的 `actionButton` / `runAction`；结果写在按钮上（`installed` / `pending` / `failed` 可再点 / 连不上可再点）。
  离线快照里按钮是灰的。待处理项在数据里多一个 `action: {name, agent, side}`（`Graph.quest(..., action=)`），别的待处理项没有。

```mermaid
flowchart LR
    Q["设置窗口（另一个进程）<br/>「到配置全景里改」"] -- "写 overlay-settings-command.json<br/>open_panorama + focus=组" --> M["主进程<br/>壳 / AppShell 消费指令"]
    M -- "open_config_panorama(focus)" --> S["PanoramaService.open"]
    S -- "浏览器打开 …/#令牌&settings=组" --> B["boot.js：取走令牌，抹掉地址"]
    B -- "第一张图画完 → openSettings(组)" --> P["选中那块磁贴，打开设置面板"]
    T["磁贴详情的「设置」按钮"] --> P
    P -- "GET /api/settings/组" --> F["form.js 画表单"]
    F -- "api.patch：PATCH {base, changes}" --> W["写入链路（上一节）"]
```

- **哪块磁贴有「设置」按钮**：功能表（`features.py`）里那项功能的配置键，在设置表里登记了一组（`settings_table.group_for_config_key`），
  图上的节点就带 `settings: <组 id>`，页面据此出按钮；这块磁贴就不再写「去设置窗口哪一页」（`page`），测试守着两者不同时出现。
  离线快照里按钮是灰的，悬停说为什么。
- **面板跨重画存活**（`settings.js`）。改完一项，服务重新发布一次图，页面原地重画、`interact()` 整个重跑——可打开着的面板和里面
  打了一半的字不能跟着没。所以面板是整页只有一个的东西：第一次调 `settingsPanel()` 时建好、之后每次重画拿到的都是它；它的
  监听不挂在那一次画图的中止信号上（这是页面上唯一一个这样的监听），表单的监听挂在表单自己的宿主元素上，面板关掉时随元素一起扔掉。
- 关面板（按钮、点外面、Esc）时有没保存的文字：先在标题栏说一句，再关一次才丢。别的组还开着、又有没保存的字时，不切换。
- **写请求**是 `boot.js` 给的 `api.patch`：JSON、PATCH、带令牌头；浏览器自己带上 `Origin` 和 `Sec-Fetch-Site`，过的是同一套守门。
  服务的每一种回答（包括 4xx、5xx）原样交给表单，只有连不上才算失败。
- **从设置窗口跳过来**：按钮（`pet/settings_moved.py` 的 `moved_row`，以后每搬一组都用它）经设置进程 → 主进程的指令通道
  （`overlay_settings_command`，指令 `open_panorama`，`focus` 只许是 `[a-z][a-z0-9_]*` 的组名）请主进程打开配置全景。
  overlay 拓扑由壳消费、转给 `AppShell.open_config_panorama(focus)`，legacy 拓扑由 `AppShell` 自己消费；主进程没在跑时指令
  两分钟后作废。`PanoramaService.open(focus)` 只认设置表里有的组，把 `&settings=<组>` 接在令牌后面——同在 `#` 片段里，
  不发给服务器、不进日志，页面取走后整段从地址栏抹掉。服务起不来、退回离线快照时不带组名。
- **升级时开着的旧设置窗口**：它跑的是旧代码，里面还有搬走的那一组，一保存就把页面改的值盖回去。主进程启动 2.5 秒后发现设置窗口
  已经开着，就弹一条通知请用户关掉重开（`AppShell._warn_settings_window_from_before`，跟着「系统通知」总开关）。不替用户关：里面可能有没存的改动。

### 报告页：在浏览器里读生成出来的内容（工作简报、个人简报）

本机服务的第二类页面（2026-11-19，[ADR 0018](adr/0018-content-pages-move-to-the-browser.md)）：`/report/<名字>` 是公开的外壳
（无数据），`/api/report/<名字>` 要令牌，和 `/api/graph` 一样认 `?after=<编号>` 等更新的。

- **登记**：应用构造 `PanoramaService` 时传 `reports={"work_briefing": …, "personal_briefing": …}`（`reports.py`）。provider 在**界面线程**上被调
  （它读 Qt 对象），返回固定字段的字典：`title / theme / summary / generated / usage[] / html / busy / busy_text / empty_text /
  error / action{name, report, label, hint} / actions[] / available / details[] / settings_focus`。页面（`report.js`）只按字段摆，不认识功能。
  `actions[]` 是主按钮旁边的副按钮（同一种字典，走同一个动作通道；个人简报的「记灵感…」回 `opened`，页面在状态栏说一声）。
  `details` 是「这次是怎么生成的」那几段 `{title, html}`（服务端渲染、全部转义，见[公司侧助理](work-assistant.md)的
  「运行记录」），页面折叠着摆在全文下面、第一段默认展开；里面的 `__SETTINGS_URL__` 占位由页面换成
  `/#<令牌>&settings=<settings_focus>`（同一个服务、同一个令牌）。
- **分区、筛选、勾掉**（2026-11-20 改版）：provider 把渲染好的全文按 `<h3>` 切成 `sections[]`（`reports.split_sections`：每区
  `id / source / title / html` 和顶层条目的计数 `count / p3 / p2 / p1 / bugs / updated`；`source` 只是按标题关键词猜的来源，
  配色用）。页面：顶栏 sticky（标题 · 生成时间 · 用量 · 状态 · 「重新生成」），概要大字；≥ 980px 两栏——左栏 240px 贴着滚：
  每区一块实色磁贴（点了滚过去）、筛选片（`全部 / ★★★ / ★★ / ★ / 🐞 bug / 有更新`，多选取并集）、「隐藏已勾掉」、
  「这次是怎么生成的」锚；右栏每区一张卡（实色磁贴头 + 计数徽章 + 折叠）。窄屏单栏，磁贴变成顶部一行横滚。
  进页面后 `report.js` 给每张卡里**顶层**的每一条打 `data-p / data-bug / data-upd`（`items.classify`：开头的 ★ 类名、
  `li.bug`、行里的 `<strong>`）并插一个勾选框；勾掉只存这个浏览器的 `localStorage`（键 = 报告名 + 生成时间 + 区 + 序号，
  重新生成就是新的一套），不进肥鱼、不进配置。分类与筛选是纯函数（`items.js`），QJSEngine 里直接测；DOM 接线只在真浏览器核对。
  没有 `<h3>` 的内容（老简报、空内容）退回整段 `article`。
- **数据怎么到页面**：每份报告自己一个 `Feed`。第一次 `GET /api/report/<名字>` 时还没发布过，请求线程经 `on_gui` 让界面线程做一份
  （`publish_report(force=True)`）；之后页面带编号等更新。简报服务 `started` / `finished` 时应用调 `publish_report(name)`——
  **没人打开过页面就什么都不做**（provider 不白跑）。`report_watched(name)` = 有请求挂在那份报告上 = 用户正开着看，
  控制器据此不再为新一份冒提醒。
- **打开**：`open_report(name)` 起本机服务（不采集全景那一轮）、`publish_report(force=True)`、开 `base_url/report/<名字>#令牌`。
  报告没有离线快照：服务起不来就返回 False，调用方冒气泡。
- **Markdown → HTML 在 Python 里**（`markdown.py`）：标题、列表（可嵌套）、段落、粗体、行内代码 → `<code class="chip">`、
  `[文字](http(s)://…)` 和裸地址 → 新标签页的链接（别的协议只是几个字）；列表项开头的 ★ → `<span class="star s1|s2|s3">`，
  bug 记号开头的项 → `<li class="bug">`（它的子列表随它上底色）。这几条就是原来 Qt 窗口 `_decorate` 的上色规则。
  其余一律转义：`<script>` 只是几个字。
- **样式**：`report.css` 用 `tokens.css` 的 `--m-*`（跟「外观」里的主题：provider 给 `theme`，页面设 `data-theme`），顶部那组
  链接色 / 小标签 / bug 底色 / 星色和 Qt 壳的 `_EXTRA_TOKENS` 一字不差。没有圆角。页面上不放明暗切换（偏好只在一处改）。
- **「重新生成」**：`POST /api/actions/generate_report {report}` → `generate_briefing`（按报告名分发）→ `started / busy / failed / unavailable`。
  个人简报页的「记灵感…」：`POST /api/actions/open_inspiration {report}` → `open_inspiration` → 界面线程上开 Qt 窗口的灵感页 → `opened`。
  回 `started` 页面不动按钮，等 `started` 信号带来的重画把它变灰、`finished` 再放开。
- **隐私**：内容不进全景图、不落快照、不进日志（服务只记请求行）；只经带令牌的接口给 `127.0.0.1` 上的浏览器。
- 两张页共用 `client.js`（取令牌、`api` / `api.patch` / `api.post`）；`items.js` 是报告页的纯函数；`report.js` 是会自己跑起来的入口，**不在 `MODULES` 里**
  （不能拼进全景的离线快照）。

### 笔记页：看、记、处理工作笔记；Slack 关注的状态与存档（2026-11-20，M4b 第三、四项）

报告类页面的第二种外壳。登记方式和报告页一样（`reports={"work_notes": notes.work_notes(…)}`），不同的只是 provider 函数带属性
`page = "notes"`：服务记在 `_report_pages` 里，`GET /report/work_notes` 发 `notes.html`（`render.report_shell("notes")`），数据里的
`strings` 换成 `render.NOTES_KEYS` 那套。Feed / `publish_report` / `report_watched` / `open_report` 原样复用；`open_report(name, note=)`
把要选中的那条放进片段（`#<令牌>&note=<名字>`，`client.takeToken` 把令牌后面的段原样交给页面）。

- **provider 给什么**（`notes.py` 模块说明有全表）：`notes[]` 每条的字段、`counts`、`repo{ready, dir, status}`、`composer`（有没有输入框）、
  `watch`（Slack 页的检查状态条，笔记页是 null）、`action` / `actions`。顺序在 Python 里排好：未完成的在前（有提醒的按提醒时间，没提醒的
  按记下时间倒序），已完成的在后。要点 `details_html` 由 `markdown.render` 渲染；原文 `original_html` 只转义 + 裸链接变链接
  （`markdown.linkify`），**不当 Markdown 解析**。
- **页面**（`notes.html / notes.css / notes.js`，纯函数在 `notelist.js`）：顶栏 sticky（标题 · 待办 / 有提醒 / 已完成 计数片 · 状态 · 仓库
  状态 + 「再推一次」· 打开文件夹 · 设置）；下面是输入区（多行框 + 「记下」，Ctrl+Enter）；≥ 980px 两栏——左 380px 列表（筛选片
  `全部 / 待办 / 有提醒 / 总结中 / 已完成` 带计数、> 5 条有搜索框、每条左边 4px 类型色条 slack / jira / confluence / link / text），右详情卡
  （类型色磁贴头 + 标题 + 状态徽章、元信息、摘要大字 + 要点、原文、用量小片、动作区：完成为主按钮，打开链接 / Obsidian / 重新总结 /
  稍后 1 小时 · 3 小时 · 明天 9:00 / 删除）。选中的那条记 `sessionStorage`（刷新不丢）。
- **动作**：`POST /api/actions/note {report, op, name, text?, minutes?}` → `note_action` 在界面线程上调服务，回 `{state}`；删除前的
  确认在页面（`confirm()`，同「修复」）。页面拿到回答只在状态栏说一句，**不自己改列表**：服务发 `changed / summarized / synced`，
  应用 `publish_report("work_notes")`，页面等到新数据再重画（选中、筛选、搜索保持）。
- **Qt 侧**：`WorkNotesController(open_report=)`——提醒气泡的「查看」、菜单「工作笔记」都开浏览器到那一条；本机服务起不来时退回
  简报窗口里的「笔记」页（`WorkNotesPanel` 还在，M4b 最后一项才删）。
- **Slack 关注页**（`/report/slack_watch`）是同一张页：`composer: false`，顶上多一条**检查状态条**（`watch`：上次检查几点、多久前、
  发现几条、概要、下一次约几点 = 上次 + 间隔、失败原因、忙不忙）和「现在检查」（走报告页的 `generate_report` 动作，分发表里
  `slack_watch → SlackWatchService.check_now`）；下面是存档（仓库 `slack/` 里的笔记，`note` 动作同一个处理器，报告名区分服务）。
  没有 WSL → 整页只说一句；有 WSL 但工作笔记关着 → 只有状态条，列表空、说明写着存档要开工作笔记。检查开始 / 结束、存档变了都
  `publish_report("slack_watch")`。Qt 的 Slack 关注独立窗口只剩退路。
- 隐私同报告页：内容只经带令牌的接口给本机浏览器，不进全景图、不落快照、不进日志。

### 文件查看（只读）

图上能打开看的东西带一个「查看」按钮：`CLAUDE.md`、项目记忆、`settings.json`、大肥鱼这几块磁贴上，和存储磁贴清单里
能看的那些项旁边。
点了之后页面向本机服务要清单（`GET /api/files?store=<存储>`）再要文件（`GET /api/file?store=<存储>&path=<相对路径>`），
在盖住页面的一张面板里按纯文本显示。

- **能读什么由 `files.py` 一处把关，页面说了不算。** 一条路径过四关才会被打开：存储在 `VIEWABLE` 名单里、种类不是
  登录凭据或密钥、根读得到；路径是规矩的相对路径（没有 `..`、反斜杠、盘符、绝对路径、空段）；按存储表的模式它**正好属于
  这一项**（同一个项目目录下的会话原文不属于「项目记忆」）；路径上**不经过任何符号链接或目录联接**，是普通文件——
  解开链接后的真实位置必须正好是「根 + 这条路径」。只查「还在根里面」不够：根里面的一个链接能让一条看着属于
  「项目记忆」的路径，真身落在登录凭据上。
- **WSL 一侧的文件经 `wsl.exe` 读**（`claude_settings_wsl`、`claude_md_wsl`、`claude_memory_wsl`、`claude_skills_wsl`）。
  前三关照旧在这边过，过不了的根本不会起进程；第四关只有在 WSL 里面才守得了，由 `wsl_file_agent` 守。请求（含路径）写成
  喂进去的源码里的一个字符串字面量，不经过 `wsl.exe` 的命令行，空格、引号、中文都不用转义；回答只用 ASCII。
  那边没回话（没装 WSL、超时、回的不是 JSON）是 `unavailable` → 503。一次列或读大约 0.1 秒（发行版醒着时）。
  哪一关没过都只回短代码（`not_viewable` / `bad_path` / `not_found`），不带内容、不说原因。
- **名单里的文件原样给，不脱敏**（2026-11-16 定的：能打开这个页面的只有本人，设置文件、JSON 文件直接看原文）。
  所以这道门守的是**范围**不是内容：名单外的、根目录外的，一个字也拿不到；名单里的，里面有密钥也照给。
- **名单**（`files.VIEWABLE`）：设置（肥鱼的 `config.json` 和分身的、Claude Code 的 `settings.json` 等、`~/.claude.json`）、
  人和 AI 写的文字（`CLAUDE.md`、项目记忆、技能 / 子代理 / 命令、蒸馏条目和提案、聊天记录、待办、消息记录）、
  JSON 簿记（对话列表、配置备份的簿记、蒸馏和各功能的簿记）。
- **永远不给看的**：登录凭据（`.credentials.json`）和钥匙串。`viewable()` 按种类再拦一次，名单里写了也没用——
  看它们的原文没有用处，截图或投屏时却会泄漏。**现在没放进名单的**：图片 / 音效 / 语音缓存（不是文字）、会话原文、日志、
  缓存（量大，要看再加）。家目录不会被走一遍：那个根下只认存储表里写了确切名字的 `.claude.json`。
- 不是文字的文件（开头 8 KB 里有 NUL 字节）不给内容，只说「不是文本文件」。技能目录里夹着图片时会遇到。
- **图只在真有东西可看的地方给按钮**：存储在名单里，并且存储探针刚才数到这台机器上有它的文件（`sources._can_view`）。
  WSL 一侧同理，但要那边的探针数过存储（结果里有 `storage`）才给。
- **文件内容永远当文本**：`viewer.js` 把每一行转义后放进页面，不当标记解析。记忆文件里写了 `<script>` 也只是几个字。
- **受管块**由服务标出行号（`marks`，标记串和 `claude_home_probe.BLOCK_RE` 同源），页面给这几行加底色并说明「手改会被覆盖」。
- 一个文件最多给 512 KB（超了截断并说明），一项最多列 500 个文件。清单里的短名字是模式里通配符对上的那几段加文件名
  （`<项目> / MEMORY.md`），完整路径在悬停提示里。
- **离线快照里按钮是灰的**：没有服务可问。文件内容不进快照、不进 `/api/graph`、不进日志（服务只在调试级别记请求行）。
  不脱敏只发生在这一条路上；图上和快照里的密钥仍然只留「有没有 + 末 4 位」（见下一节）。
- 面板开着的时候数据换了、页面原地重画：面板留着，监听跟着新的那一套重新挂上。

### 只读、秘密、隐私

- **只读**：探针不写任何文件，`Config` 只加载。
- **秘密不落盘**：API key 和 GitHub token 只留「有没有 + 末 4 位」，不超过 12 个字符的连末位也不留（露 4 位就是露了三分之一）；
  凭据文件只看在不在、不读内容；仓库远端地址去掉内嵌凭据。
- **页面不联网**：没有外部脚本、样式、字体；从肥鱼点开的页面只和本机服务说话（内容策略只许同源），
  离线快照是单个 HTML。快照里嵌的数据把 `</` 转义，防 `</script>` 截断页面。
- **不要令牌就能拿到的东西里没有数据**：外壳和静态文件只有结构、代码和界面文字；采到的一切只在 `/api/graph` 里，
  文件内容只在 `/api/file` 里，都要令牌。
- 页面是自用的，**不脱敏**：里面有账号邮箱、组织名、机器名、connector 名，以及两边每条记忆的名字和说明（公司侧的也在）。生成的 `%APPDATA%/big-fat-fish/panorama/panorama.html`
  不要提交或贴出去；测试样例（`tests/panorama_samples.py`）必须全是虚构的事实。

### 两段采集（`PanoramaService.open()`）

- 第一段只采 Windows 一侧（约 0.16 s）就发布、开浏览器；第二段去 WSL 探测（约 6.7 s，几乎全是 `claude mcp list`
  逐个体检 connector）后再发布一次。等全部采完再开，用户点完要干等 7 秒。
- **发布 = 两件事**（`_publish`，在后台线程上）：先写离线快照，再把 `/api/graph` 的正文整个换成新的，`revision` 加一。
  本机服务的线程只读这一个引用，从不原地改。
- **浏览器打开的是本机服务的网址**（`_page_target`，在 GUI 线程上，第一次点才创建并启动服务）；服务起不来
  （端口绑不上之类）就退回打开快照文件。网址里 `#` 后面是令牌，日志里只记 `#` 之前的部分。
- **页面等新数据是「挂一个请求」，不是隔几秒问一次**：拿到第一份之后，`boot.js` 带着它的 `revision` 请求
  `/api/graph?after=<revision>`。服务端（`Feed.wait_newer`）把请求挂住，发布的那一刻就回（实测 0.7 毫秒内）；
  挂满 25 秒还没有新的就回 204，页面隔 1 秒再来。拿到新数据后页面**原地重画**，保留选中的节点、线路筛选和搜索词，
  磁贴不重放入场动画。所以第二段探完、或者页面开着时再点一次「配置全景」，开着的那个标签页会自己换成新的。
- **标签页藏起来时不挂请求**，回到前台才接着等（期间发布过的新数据会立刻拿到）。所以服务的「空闲」实际是
  「没有看得见的页面，并且 15 分钟没动」；挂着的请求每 25 秒回一次，正好当探活用，不另设心跳。
- 请求失败（肥鱼退出、服务已自停、令牌作废）时页面亮出「连接断了」，图和选中状态留着，之后不再去敲。
- 令牌从地址栏抹掉后存在 `sessionStorage` 里，所以手动刷新也还拿得到数据。
- `aboutToQuit` 时先 `Feed.close()`：挂着的请求立刻以 204 放回去，服务才停得干净；页面随后那次请求失败，亮出「连接断了」。
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
- 设置窗口里已经搬走的那一组原处的按钮：打开配置全景并直接翻到那一组（见「改设置：页面上的入口」）。
- 「使用中的模型服务」那条线通不通，取[灵动岛](island.md)上 API 体检器**最近一次**的结论（`AppShell._panorama_health`），
  不是点击那一刻现查；没开岛或走命令行入口时是 `unknown`。

### 测试

- `tests/test_panorama_page.py` 用 Qt 自带的 JS 引擎（`QJSEngine`）加一个极简假 DOM **真跑页面脚本**：每个节点一块磁贴、
  每条线一条路径、坐标没有 NaN、磁贴不出界不重叠，四种 WSL 状态各跑一遍。脚本里写坏一处正则整页就是空白，靠它拦。
  页面脚本用到新的 DOM / BOM 接口时要给假 DOM 补上。`boot.js` 也在这里跑：假 `fetch` 同步返回、假定时器由测试触发，
  所以 `boot.js` 只用 `.then`，不用 `async` / `await`。同一个文件里还有一条用例让 JS 引擎按真正的模块规则加载 `app.js`
  （`importModule`），并要求它和拼出来的脚本画出同一张图：哪个模块导入了别人没导出的名字，或者两条交付路径分了叉，都在这里红。
  重画也在这里测：按页面的顺序 `capture → dispose → start(新, kept)` 跑两张图，看选中的节点带过去了、不存在了就放下、
  监听摘掉又挂上同样多（只差设置面板那一个整页的监听）。
- `tests/test_panorama_form.py` 跑表单本身；`tests/test_panorama_settings_panel.py` 跑入口：哪块磁贴有按钮、离线快照里是灰的、
  面板和没保存的字跨重画还在、关面板的提醒、网址里带组名就直接翻过去、`api.patch` 的请求长什么样、4xx 原样交给表单。
- `tests/test_panorama_feed.py`、`test_panorama_routes.py` 测「等新数据」：用线程加 `join` 断言结果，不赌先后——
  先发布再等、先等再发布，等的人拿到的都该是同一份。
- `tests/test_panorama_render.py` 守两条：离线快照不向任何地方要东西；外壳和静态文件里没有采到的数据、没有内联脚本。
- 页面文字全部来自 `pet/locale/*.json` 的 `panorama.*`（存储的名字和说明在 `stores.*`）；两种语言 × 四种 WSL 状态下
  建出来的图不许有缺的文字。
- `tests/test_panorama_files.py`：读临时目录里的真文件，接口那一半走真实的本机服务。拒绝矩阵是重点——名单外的存储、
  十几种不规矩的路径、属于别的存储的路径、指到根外面的链接和目录联接，各自回什么代码；密钥字样不许出现在任何回答里。
  这里**不查内容里有没有密钥**（原样给是定下的做法），查的是范围。**往 `VIEWABLE` 加一项，先在这里补它不该读到的邻居。** 查看面板在 `tests/test_panorama_page.py` 里单独跑
  （假的「向服务要东西」同步返回）：问了哪两个网址、内容被转义、受管块的行带标记、读不到时说什么。
- `tests/test_panorama_storage.py`：探针读临时目录里的真文件（归类、不认得的只报名字、封顶、缺目录）；图那一半喂虚构事实
  （三块磁贴怎么分、每一项恰好列一次、配置备份五种状态各自的磁贴和线、没登记的文件、WSL 一侧没核对时怎么画）。
- `tests/test_panorama_server.py` 用真实的回环套接字测服务：`http.client` 能随意改 Host / Origin，正好冒充浏览器里的坏页面。
  上表每一行至少一条用例；空闲自停靠注入的假时钟推进后等事件，不用固定 sleep。往路由表加接口不用重测守门，
  但**改 `_check` 的顺序或条件必须先改这里的拒绝矩阵**。

## 设计取舍

- **设置的版本用值的指纹，不用计数器**：不用落盘，两个进程算出来一样，别的组变了不影响这一组。代价是它挡的是
  「值不一样」，不是「有人动过」——动过又改回去的不算过期。
- **写接口比读配置严**：读的时候不合法的值换成默认值，写的时候同样的值直接拒。两套口径是有意的。
- **界面线程没空就拒，不排队等很久**：一次落盘是毫秒级的，等 10 秒还等不到说明界面卡住了，这时候再悄悄补写更糟。
- **起本机服务，而不是只写文件**（推翻了第一期的取舍，见 [ADR 0014](adr/0014-panorama-becomes-the-console.md)）：
  `file://` 页面不能回传，改不了任何东西。代价是多一个只在用的时候开着的回环端口，和上面那一串守门检查。
- **一份页面代码、两种交付**：离线快照把外壳、样式、脚本和数据内联成一个文件，本机服务把它们分开发。
  不维护两套页面；`boot.js` 靠有没有嵌入的数据分辨自己在哪一种里。
- **用挂起的普通请求等新数据，而不是 `EventSource` 或 WebSocket**：令牌在自定义请求头里，`EventSource` 带不了请求头
  （放进网址就进了日志和历史记录）；WebSocket 要自己实现握手和帧，标准库没有。挂起的 `fetch` 两样都不需要，
  守门检查也原样适用。代价是每个看得见的页面占一条处理线程（挂着时不占 CPU）。
- **重画是整张图重新生成，而不是比对后只改变化的部分**：图小（几十块磁贴），
  换来不需要一套差异算法；要保留的只有「用户正看着什么」这三样。
- **藏起来的标签页不等新数据**：否则一个忘了关的标签页会让服务永远不自停。代价是回到标签页时要多等一个来回。
- 垫底结果不落盘：肥鱼重启后第一次打开，WSL 一侧显示「正在探测…」。
- 自动走线**不做交叉最小化**，节点明显变多后局部可能变乱。
- **存储按「硬盘没了会怎样」分块，而不是一项一块、也不是按种类分**：这张图要回答的是「哪些东西丢了就没了」，
  按这个分，一眼看得到琥珀色的那块有多大。代价是想找某一项要点开磁贴或用搜索（搜索会搜到清单里每一项的说明）。
- **记忆的重复只按字面判，不叫模型**：便宜、每次打开都能算、不会把两条不相干的记忆说成重复。代价是漏判；
  真要语义去重，是蒸馏那边的事，不是打开一张图时该花的钱。
- **记忆的名字和说明直接放进图里**，没有做成点开再向服务要：面板要一次看全两台机器才能比对。代价是页面数据变大
  （本机实测 41 KB → 129 KB），离线快照里也多了这些内容。
- **WSL 一侧数存储，靠把三个文件的源码拼成一份喂过去**，而不是让那边只报文件清单、这边来归类：那边可能有几万个文件，
  清单要过管道，归类结果只有几十个数。代价是三个文件得守「只用标准库、顶层名字不相撞」这两条，由测试守着。
- **读 WSL 里的文件每次起一个 `wsl.exe`**，没有做常驻的代理：点「查看」是偶尔的事，0.1 秒可以接受，常驻进程要管生命周期。
- 菜单项放根菜单 tools 段而不是子菜单：一次右键就点得到，代价是根菜单又长一项（「工具与帮助」子菜单 2026-11-18 已删，ADR 0017）。旧版菜单模板
  （`pet/context_menus/legacy.py`）有意没加。
- 个人账号的 connector 只能画成「探测不到」：它们挂在 claude.ai 账号上，磁盘上只有「连过哪些」，Windows 上
  `claude mcp list` 返回空。如实画成灰点线并写进待处理，不猜。

## 外部格式依赖

「在 VS Code 打开」靠 VS Code 的链接格式（`interact.js` 里拼）：

- Windows 上的路径：`vscode://file/<路径>`。文件和目录都行，VS Code 自己去看它是哪一种。
- WSL 里的路径：`vscode://vscode-remote/wsl+<发行版>/<路径>`，在连着 WSL 的窗口里打开（要装 WSL 扩展）。
  **VS Code 对远程路径分不出文件和目录，默认当文件夹开；结尾带 `:行号` 才当文件。** 所以文件的链接拼成 `…/CLAUDE.md:1`，
  目录（来源里带 `dir`，由 `sources._src(folder=True)` 标）不带。发行版名字没探到时不给链接，只留「复制路径」。
- 两种链接结尾都带 `?windowId=_blank`：VS Code 看到它就**开一个新窗口**，否则文件会开进最近用的那个窗口，
  和手头的项目混在一起。VS Code 打开之前会把这个参数摘掉，不会变成路径的一部分。
- 依据是 VS Code 源码 `src/vs/code/electron-main/app.ts` 里处理协议链接的那两个函数（`handleProtocolUrl`、
  `getWindowOpenableFromProtocolUrl`）；VS Code 改了这些规则就要跟着改。

Claude Code 升级后先核对 `claude_home_probe.py` 读的这些：

- `~/.claude/settings.json`：`hooks`（事件 → 组 → `hooks` 列表，逐条命令计数，含 `big-fat-fish` 字样的算肥鱼的）、`model`、
  `effortLevel`、`permissions.allow`、`enabledPlugins`。
- `~/.claude.json`：`oauthAccount.emailAddress` / `organizationName`、`mcpServers`、`claudeAiMcpEverConnected`。
- `~/.claude/plugins/installed_plugins.json` 的 `plugins`；`~/.claude/.credentials.json`（只看在不在）。
- `~/.claude/projects/<目录名>/`：目录名 = 项目绝对路径里非字母数字的字符全换成 `-`；里面每个 `*.jsonl` 是一次会话，
  开头几行带 `"cwd"`。`~/.claude.json` 的 `projects.<路径>` 下有 `lastCost`、`lastDuration`（毫秒）、`lastLinesAdded`、
  `lastLinesRemoved`。
- `claude mcp list` 的输出行 `名字: 地址或命令 - 状态`：按首个 `: ` 和末个 ` - ` 切（命令里可以有空格）；状态含 `Connected` = 通，
  含 `authentication` = 待授权，其余 = 坏。中间那一段以 `http://` / `https://` 开头算远程服务，否则算本地命令。
- `~/.claude.json` 的 `mcpServers` 和 `projects.<路径>.mcpServers`：每个服务器的 `type`、`url` 或 `command` + `args`、`env`、`headers`。
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
| WSL 一侧一直「正在探测…」 | 第二段没发布：看日志里「配置全景：WSL 一侧探完」；发行版冷启动 + connector 多时会更久（上限 150 s）。标签页在后台时不会更新，切回来就换 |
| 数据换了页面没跟着变 | 标签页是藏着的（切回来才接着等）；或页面顶上已有红条「连接断了」（那之后不再问）。浏览器开发者工具的网络面板里应当有一个挂着的 `graph?after=…` |
| 重画一次，点一下磁贴触发两次 | `interact` 里新加的监听没带中止信号 `on`，旧的那套没被摘掉 |
| WSL 一侧显示失败 | 探针在发行版里退出码非 0 或输出不是 JSON（那边要有 `python3`）；`python -m pet.panorama --no-mcp --no-open` 复现 |
| 模型服务的线是灰点线 | 没开岛（没有体检器）或走的命令行入口；正常 |
| hooks 的线是红色断线 | 如实反映：联动开着，但那一侧 `settings.json` 里没有肥鱼的 hook（被卸掉过），去重新安装 hooks |
| 功能明明开了却显示未启用 | 显示的是生效值：看该功能的总开关 |
| 点「在 VS Code 打开」开出一个空白窗口 | WSL 里的文件被当成文件夹开了：链接结尾少了 `:1`（来源被错标成了目录），或 VS Code 改了规则。见「外部格式依赖」 |
| 「在 VS Code 打开」把文件开进了现有的窗口 | 链接结尾少了 `?windowId=_blank`，或 VS Code 改了规则。见「外部格式依赖」 |
| WSL 一侧的磁贴没有「在 VS Code 打开」 | 发行版名字没探到（探针读的是 `WSL_DISTRO_NAME`）；路径仍然可以复制 |
| 「项目与会话」里很多项目的路径是「不知道」 | 那些项目没在 `~/.claude.json` 里登记，会话记录里的目录又和文件夹对不上（常见于在工作区里开的会话）。不猜 |
| 「项目与会话」说有上千个空的项目目录 | 如实反映：`~/.claude/projects` 下攒了很多既没有会话也没有记忆的目录。它们不占多少地方，但会拖慢按目录找东西的工具 |
| 连接器那一行下面没有「连到哪」 | 那是个人账号在 claude.ai 上的连接器（本机只知道连过），或者这一轮没有跑 `claude mcp list` |
| 「上次探测」后面一直挂着「正在重新探测」 | WSL 那一半的新结果还没到：标签页在后台时不更新，切回来就换；一直不换看日志里「WSL 一侧探完」 |
| 连接器的命令行里露出了一段像密钥的东西 | 它是当位置参数写的，没有 `--token` 这样的名字可认。把它挪到环境变量里，或者告诉我加规则 |
| 「记忆一览」里某个项目重复出现、几乎每条都标着「像是全局的」 | 同一个仓库的多个工作区各有一个项目目录，各带一份记忆：如实反映，不是误判 |
| 「记忆一览」里明显重复的两条没被标出来 | 标题和说明的字面都不一样。这里只按字面判 |
| 「记忆一览」里 WSL 那一栏没有 | WSL 那半张图还没探完或探失败了；探完会原地补上 |
| WSL 一侧的文件点「查看」说读不到 | 浏览器网络面板里看 `/api/file` 的回答：503 `unavailable` 是 `wsl.exe` 没回话（发行版没起来、超时）；400 `bad_path` 多半是路径上有符号链接 |
| WSL 一侧的存储磁贴没有数目 | 图上垫着的是肥鱼升级前那一轮的 WSL 结果；等这一轮探完会补上 |
| 生成 WSL 探针源码后那边报语法错或 `NameError` | 三个拼在一起的文件里有人 import 了标准库以外的东西，或者定义了同名的顶层名字；跑 `tests/test_panorama_wsl_side.py` |
| 改设置得到 409 `stale` | 这一组的值在页面读过之后变了（设置窗口、另一个标签页、或者别的写入）。回答里带着现在的值，重读再改 |
| 改设置得到 422 `invalid` | 回答的 `errors` 里是哪几项：`rejected` = 功能自己的校验不认（时间要写成 `HH:MM`，模型名只认字母数字和 `. _ -`）；`out_of_range` = 数字超出设置表里声明的上下限；`not_a_choice` = 不在可选值里；`unknown` = 表里没有这一项 |
| 改设置得到 503 `busy` | 界面线程 10 秒没空。这次写入已经作废，没有存；等肥鱼缓过来再试 |
| 表单里打的字点了保存却没交出去 | 那一项依赖的开关关着（变灰了），或者上一次保存还没回来（整张表单是灰的） |
| 改设置得到 409 `unavailable` | 这一组在这台机器上用不了（工作简报要 WSL） |
| 设置窗口里点「到配置全景里改」，浏览器没打开 | 主进程要在跑（它三秒内取走 `overlay-settings-command.json`）；日志里找「收到设置进程指令 → 打开配置全景」。没有这行就看配置目录里那个文件还在不在、是不是超过两分钟作废了 |
| 页面上改好的工作简报设置又变回去了 | 多半是升级前就开着的设置窗口（旧代码，里面还有这一组）保存了一次。关掉重开；肥鱼启动时发现它开着会弹通知提醒 |
| 磁贴上没有「设置」按钮 | 那项功能的设置还没搬过来（还在设置窗口，磁贴上写着哪一页）；或者这是离线快照，按钮是灰的 |
| 「查看」按钮是灰的 | 打开的是离线快照（地址栏是 `file://`）：没有服务可问。从肥鱼里点「配置全景」打开 |
| 该有「查看」的地方没有按钮 | 存储不在 `files.VIEWABLE` 里（登录凭据、钥匙串永远不在）；或存储探针没数到这台机器上有它的文件；或它在 WSL 一侧 |
| 查看面板说「读不到」 | 文件刚被删了 / 改名了，或服务停了（页面顶上会有红条）；浏览器网络面板里看 `/api/file` 回的代码 |
| 多出一块「没登记的文件」 | 数据目录里有存储表不认得的文件：新功能忘了登记就去 `pet/data_stores.py` 加一项；别的程序或早先版本留下的，确认后删掉文件 |
| 存储磁贴上各项都不显示数目 | 那个地方没逐个文件核对（WSL 一侧），或者 `facts` 里没有 `storage` 这一段（探针抛了异常，看日志） |
| 「有备份机制」是琥珀色 | 如实反映：配置备份没开、没填仓库且没配知识库仓库、没有 GitHub Token、上次失败、或暂停了；点开看是哪一种 |
| 页面调接口得到 421 | Host 不是 `127.0.0.1:<端口>`：用 `localhost` 打开的，或者经过了代理 / 端口转发。只能用 `page_url()` 给的网址 |
| 页面调接口得到 401 | 令牌不对：服务空闲自停后重启过（新令牌），这个标签页是旧的；重新点一次「配置全景」 |
| 页面调接口得到 403 | 请求不是页面自己发的（Origin 或 `Sec-Fetch-Site` 不对），或写请求没带 Origin（非浏览器的调用方要自己带上） |
| 加了探测目录后全仓库守卫变红 | `TOOL_DIRS` 或样例里的名字撞了 `test_product_copy_has_no_external_brand_reference` 禁用的词 |
