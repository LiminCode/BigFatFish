# PR 报告：GitHub 连接器（桌宠对话里只读查询 GitHub）

> **基线**：`3031682`（feat(character): 新增内置角色 Claude）
> **分支**：`feature/claude-session-fish`　**日期**：`2026-10-11`
> **范围**：13 个文件（实现 9、测试 2、文档 2 含本报告）
> **关联**：Claude 通道见 [`PR-REPORT-CLAUDE-CODE-SESSION-FISH-2026-10-11.md`](PR-REPORT-CLAUDE-CODE-SESSION-FISH-2026-10-11.md)；
> 设置准入见 [`SETTINGS-CHANGE-GATES.md`](SETTINGS-CHANGE-GATES.md)

## 一、核心特性

桌宠的对话此前只带消息、不带任何工具，问它「我仓库最近有什么提交」只能回答
「我连不上你的账号」。本改动给 Claude 通道加了一个 **GitHub 连接器**：开关打开并填入
Personal Access Token 后，对话请求会带上 GitHub 官方远程 MCP 服务器，由 Anthropic 的
服务器替模型调用工具，桌宠本地不跑 MCP 客户端、不直接请求 GitHub。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 对话里查 GitHub | 仓库、提交、文件内容、Issue、PR（GitHub MCP 的默认只读工具集） |
| 2 | 只读 | 地址固定为 `https://api.githubcopilot.com/mcp/readonly`，GitHub 侧只暴露读工具 |
| 3 | 设置页开关 | 「AI 与对话 → 连接器」：开关 + Token 输入框；Token 存系统钥匙串 |
| 4 | 失败可读 | Token 失效时报「连接器出错，请检查 Token 或先关掉连接器」，不是一句英文 400 |

**红线 / 不变量**

- 连接器关闭（默认）时，发出的请求与改动前**逐字段相同**
  （`test_requests_without_connectors_are_unchanged`）。
- Token 不落盘：只在系统钥匙串里；运行期挂在 `ProviderConfig.mcp_servers` 上的副本
  永远不进 `to_dict()`（`test_the_switch_persists_and_the_token_never_reaches_disk`）。
- 只有交互式对话（现代聊天窗、经典聊天窗、快捷对话气泡）挂连接器。识屏、主动识屏、
  文件解读、Agent 联动等后台请求不挂。
- 只在**直连** `api.anthropic.com` 时挂。OpenAI 兼容通道没有这个功能；经第三方网关访问
  Claude 时不挂，Token 不交给网关。

## 二、修改文件说明

增删行数取自 `git diff --numstat`（相对基线 `3031682`）。

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/chat/connectors.py`（新增） | +45 / −0 | 决定「这次对话挂哪些 MCP 服务器」的唯一位置。`mcp_servers_for(settings, provider)`：开关开着、Provider 直连 Claude API、钥匙串里有 Token 三者同时满足才返回一项，否则空列表。常量 `GITHUB_MCP_URL` / `GITHUB_TOKEN_REF` 在这里 |
| `pet/chat/anthropic_provider.py` | +43 / −11 | `_open_stream` 多一个 `mcp_servers` 参数：非空时加 beta 头 `mcp-client-2025-11-20`、`mcp_servers`、成对的 `mcp_toolset`，并开两处提示缓存（见 §三）；与拒答回退的 beta 可并存。`AnthropicProvider.stream` 改成循环：回合以 `pause_turn` 收尾时把这一段接回去续跑，最多 4 次。`_translate_error` 把 `mcp_servers…` 开头的 400 翻成指向设置页的中文提示 |
| `pet/chat/models.py` | +8 / −3 | `ChatSettings.github_connector`（默认 `False`，读写 `chat.github_connector`）；`ProviderConfig.mcp_servers`（运行期字段，`to_dict` 里剔除） |
| `pet/config.py` | +6 / −0 | `Config.resolve_mcp_servers(provider)`，与既有的 `resolve_api_key` 并列，供发送点调用 |
| `pet/chat/widgets.py` | +1 / −0 | 现代聊天窗 `_begin_generation`：发送前填 `config.mcp_servers` |
| `pet/chat/legacy_widgets.py` | +1 / −0 | 经典聊天窗同上 |
| `pet/quick_chat.py` | +1 / −0 | 快捷对话气泡同上 |
| `pet/chat/ai_settings_page.py` | +35 / −0 | 新分组「连接器」两行：`github_connector` 开关、`github_token` 密码框（开关关着时隐藏）。保存时 Token 非空才写钥匙串；写不进去则弹警告并把开关存成关 |
| `pet/modern_settings_dialog.py` | +1 / −0 | 把这两行登记到「AI 与对话」页的「连接器」分组 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_github_connector.py`（新增） | +402 / −0 | 16 条：请求形状（带连接器 / 不带 / 与拒答回退并存 / 识屏不带）、`pause_turn` 续跑与上限、Token 被拒的提示、挂载条件矩阵、持久化与不落盘、`Config.resolve_mcp_servers`、三个对话入口的接线、设置页保存 / 行可见性 / 钥匙串不可用 |

| `tests/test_architecture.py` | +3 / −1 | `modern_settings_dialog.py` 行数预算 2395 → 2396（带日期注释）。该文件改动前正好等于预算，本次只加了 1 行分组登记；控件、说明文字、保存逻辑都在已拆出的 `chat/ai_settings_page.py`，没有可再拆的部分，按该测试自述的约定随实测校准 |

### 文档

| 文件 | 改动 |
|---|---|
| `docs/PR-REPORT-GITHUB-CONNECTOR-2026-10-11.md`（新增） | 本报告 |
| `docs/INDEX.md` | 「PR 报告存档」登记一行 |

### 未改动

- `pet/chat/settings_dialog.py`（经典聊天窗里的即存设置对话框）：不加入口。按
  [`SETTINGS-CHANGE-GATES.md`](SETTINGS-CHANGE-GATES.md)「归属唯一」，开关只在主设置页
  有一处；该对话框保存时重新读取 `config.chat_settings()` 再写回，开关值原样保留。
- `pet/file_interpret.py`、`pet/proactive.py`、`pet/vision.py`、`pet/agent_link.py`、
  `pet/overlay_shell.py`、`pet/window.py` 里的其它 `resolve_api_key` 调用点：故意不挂
  连接器（后台请求，见红线）。
- `CONTEXT.md`：没有改 Shared UX Contract / Settings System / Menu Action Model，不更新。

## 三、实现要点

**为什么用 MCP connector 而不是本地工具。** 两条路都能做：(A) 请求里带 `mcp_servers`，
Anthropic 服务器去连远程 MCP；(B) 桌宠自己定义工具并本地调 GitHub REST API。选 A：
桌宠侧只是请求多几个字段，没有工具循环、没有本地 HTTP 客户端；GitHub 官方 MCP 服务器
直接接受 PAT 当 Bearer token，不需要 OAuth 流程。代价写在 §七。

**请求形状。** `mcp_servers=[{type:"url", url, name:"github", authorization_token}]` 与
`tools=[{type:"mcp_toolset", mcp_server_name:"github"}]` 必须成对，只带前者会被 API 拒掉。

**缓存。** GitHub 默认只读工具集的定义约 1.23 万 token，每次采样都要带。开两处缓存：

1. `mcp_toolset` 上的 `cache_control`：断点落在工具定义末尾，**跨会话**命中（工具定义
   与系统提示、消息内容无关）。
2. 顶层 `cache_control`：同一会话的后续轮次、以及工具调用后的续写命中。

只开第 2 处时，两条不相关的消息之间不命中（实测 `cache_read=0`，见 §四），因为自动
缓存只在整段前缀末尾写一条记录。

**`pause_turn`。** 服务端工具跑得久时 API 分段返回。把 `final.content` 原样作为
assistant 消息接到 `messages` 末尾再发即可续上；上限 4 次，超过抛 `ProviderError`。
本机 15 次成功的真实请求都是一次 `end_turn`，没有遇到 `pause_turn`——这条分支只有
替身测试覆盖（§七）。

**挂载点。** 沿用 `resolve_api_key` 的既有模式：对话入口在 `service.send` 前就地给
`ProviderConfig` 填运行期字段。`ChatService`、`RoutingProvider` 的签名都没动。

**设置准入记录**

```text
setting_id            github_connector / github_token
domain_id / group_id  AI 与对话 / 连接器
default               关 / 空
capability            仅直连 Claude API 时生效（不满足时开关仍可见，说明文字写明条件）
disclosure_level      primary
dependency            github_token 行依赖 github_connector（关时隐藏）
commit_policy         on_finish（随设置窗「保存」）
migration             新键 chat.github_connector，缺省读作 False；无旧键
recovery              关掉开关即回到改动前的请求；Token 在钥匙串条目 connector/github
```

## 四、性能分析

**方法（可复现）**：以真实配置的副本构造 `Config`，走
`connectors.mcp_servers_for` → `AnthropicProvider().stream(...)`，同一问题
「用一句话介绍一下你自己。」连接器开 / 关交替各 5 次；记录首段文字到达时间与
`usage`。环境：Windows 11 10.0.26300，Python 3.13.15，`anthropic` 1.13.0，
模型 `claude-sonnet-5`，effort `medium`，直连 `api.anthropic.com`。

| 指标 | 实测 | 归属 |
|---|---|---|
| 首段文字到达，连接器关（n=5） | 3.1 / 2.9 / 2.9 / 2.7 / 2.9 s，均值 2.90 s | 既有 |
| 首段文字到达，连接器开、不触发工具（n=5） | 3.4 / 3.5 / 3.4 / 3.6 / 3.9 s，均值 3.56 s（**+0.66 s**） | 新增 |
| 输入 token，连接器关 | 455（无缓存） | 既有 |
| 输入 token，连接器开、缓存命中 | 2 未缓存 + 12,309 缓存读 | 新增 |
| 输入 token，连接器开、5 分钟内首条 | 2 未缓存 + 12,310 缓存写 | 新增 |
| 只开顶层缓存时，两条不相关消息之间 | 第二条 `cache_write 12310 / cache_read 0`（不命中） | 已弃用的方案 |
| 加 toolset 断点后，两条不相关消息之间 | 第二条 `cache_write 583 / cache_read 11724`（命中） | 新增 |
| 触发工具的一问（PR 数 + Issue 数 + 最近提交，3 次并行工具调用，n=1） | 首段文字 6.9 s，总计 10.8 s；`cache_write 13235 / cache_read 12350`，输出 679 | 新增 |
| 触发工具的一问（读 README，2 次串行工具调用，n=1） | 首段文字 8.4 s，总计 11.5 s；`cache_write 7011 / cache_read 38180`，输出 517 | 新增 |
| `SecretStore().get("connector/github")`（Windows 凭据管理器，n=20） | 中位 0.06 ms，最大 1.66 ms | 新增，每次发送 1 次 |
| 新测试文件 | 16 条 0.82 s | — |

**结论**

1. **稳态开销（连接器关）**：请求字段不变；每次发送多一次 `Config.chat_settings()`
   解析与一次布尔判断，不读钥匙串、无网络。没有单独计时这一步（它在 2.9 s 的请求前
   同步执行，量级由上表的钥匙串读取 0.06 ms 可见更小）。
2. **新增路径（连接器开）**：每条消息首段文字晚约 0.66 s（5 对样本的均值差，样本小、
   未做显著性检验）；每条消息多约 1.23 万 token 的缓存读。按 Claude Sonnet 5 的标价
   折算（输入 $2/MTok，缓存读按 0.1×、缓存写按 1.25×，为推算值不是账单）：命中时约
   $0.0025/条，5 分钟内首条约 $0.031/条。触发工具时还要加上工具返回内容的 token，
   随问题而变（上表两例输入合计约 2.6 万 / 4.5 万 token）。
3. **新的系统调用 / 网络 / 磁盘 / 线程**：本机每次发送多一次钥匙串读取（开关开着时）。
   **没有**新的本机网络目的地——到 GitHub 的连接由 Anthropic 服务器发起，桌宠仍只连
   `api.anthropic.com`。没有新线程、没有新的磁盘写入（Token 只在保存设置时写钥匙串）。
4. **内存**：没有新增缓存或常驻对象；`mcp_servers` 是每次发送重建的一个单元素列表。

## 五、实机运行记录

全部在本机真实环境执行：真实 Claude API Key（桌宠配置里的 `api-2`，钥匙串读取）、
真实 GitHub classic PAT。命令里的脚本是会话内的一次性探针，未入库。

**前提的现场复现（改动前）**：用户截图——在桌宠聊天窗问「你能连接到我的 google drive
或者 gmail 吗」，回答「我没办法真正地连接到……我压根没有被赋予这样的接口和权限」。
代码侧对应 `_open_stream` 只发 `model / messages / system`，没有 `tools`。

**可行性探针（改动前，直接调 SDK）**

```text
provider=api-2 model=claude-sonnet-5 key=有 mcp=https://api.githubcopilot.com/mcp/x/repos/readonly
stop_reason=end_turn elapsed=5.3s first_text=4.1s
[mcp_tool_use] github.list_commits {"owner": "LiminCode", "repo": "BigFatFish", "sha": "main", "perPage": 3, ...}
[mcp_tool_result] is_error=False
[text] LiminCode/BigFatFish 仓库 main 分支最近 3 条提交的标题：1. Merge pull request #3 … 2. merge: 把 main（PR #2 的压缩合并）并回分支 3. fix(island): …
```

返回的三条提交与本地 `git log origin/main -3`（`be21086` / `1fc0a36` / `352ee95`）一致。classic PAT 可用，未要求 Copilot 订阅。

**改动后，走桌宠自己的代码路径**（`Config` → `connectors` → `AnthropicProvider.stream`，
系统提示用配置里的角色设定）

```text
问：我 GitHub 上 LiminCode/BigFatFish 这个仓库现在有几个打开的 PR 和 issue？最近一次提交是什么？
答：打开的 PR：0 个；打开的 Issue：0 个；最近一次提交：SHA be21086，作者 Limin Wang，
    时间 2026-10-12 01:10:01 UTC，内容：合并 PR #3「灵动岛：隐藏桌宠后「显示桌宠」…」
-- first_text=6.9s total=10.8s requests=1
-- stop_reason end_turn | blocks ['thinking', 'mcp_tool_use'×3, 'mcp_tool_result'×3, 'text']
```

```text
问：今天有点累，陪我聊两句。          （不需要工具的闲聊）
-- stop_reason end_turn | blocks ['text']      ← 没有调用任何 GitHub 工具，角色语气不变
```

**失败路径**：把 Token 换成 `ghp_` + 36 个 0

```text
-- ProviderError status=400: HTTP 400: 连接器出错，请检查 Token 或先关掉连接器（设置 → AI 对话 → 连接器）：
   Error code: 400 - {... "mcp_servers[0] 'github': Authentication error while communicating with MCP server. Please check your authorization token." ...}
```

注意这是**整条请求失败**：Token 失效期间，开着连接器的对话一条都发不出去，直到修正
Token 或关掉开关。提示文字因此直接指向设置位置。

**真实桌宠的启用**

```text
keyring available: True | saved: True          ← Token 写入 Windows 凭据管理器 connector/github
before: False | active: api-2 claude-sonnet-5
after: True | servers: ['github']              ← 真实 config.json 的 chat.github_connector
2026-10-11 21:10:11 acquired pid=56068 …       ← 桌宠已用新代码重启
```

**设置页**：真实 Windows 窗口渲染（非 offscreen）截图 4 张——窗口宽 1100 / 720 ×
开关开 / 关。开关关时 Token 行隐藏；720 宽下说明文字换成三行、Token 输入框换到说明
下方，没有裁切，横向滚动条最大值为 0。截图留在会话临时目录，未入库。

**没有自动验证的部分**

- **在真实聊天窗里打字提问**：本会话没有驱动真实桌宠窗口的输入。窗口 → `service.send`
  这一段由 Qt 测试覆盖（三个入口都断言发出的 `config.mcp_servers`），`send` 之后的一段
  由上面的实机请求覆盖；两段没有在同一个真实窗口里连起来跑过，需要用户在桌宠里问一句
  确认。
- **macOS / Linux**：未运行。钥匙串走 `keyring`，三端同一接口；设置行没有平台分支。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests scripts` | All checks passed |
| 空白检查 | `git diff --check` | 通过 |
| 红 → 绿 | `pytest -q tests/test_github_connector.py` | 改动前：收集即失败（`cannot import name 'connectors'`）；改动后：16 passed |
| 架构红线 | `pytest -q tests/test_architecture.py` | 首次运行 `test_modern_settings_dialog_py_line_budget` 红（2396 > 2395），校准预算后全部通过 |
| 聚焦 + 相关 | `pytest -q tests/test_github_connector.py tests/test_anthropic_provider.py tests/test_chat_subsystem.py tests/test_config_key_migration.py tests/test_config_domains.py tests/test_file_interpret.py` | 248 passed, 1 skipped |
| 受影响时序族满载 3 遍 | — | 不适用：新测试没有线程、定时器或事件循环等待，全部同步断言 |
| 全量 | `python -m pytest -q -p no:cacheprovider`（`QT_QPA_PLATFORM=offscreen`，`APPDATA` 指向临时目录，PowerShell 启动） | 见本节末「全量结果」 |

**全量结果**：`5 failed, 4894 passed, 11 skipped in 474.46s`。5 个失败里：

- 4 个是本机既有的环境性失败，与本改动无关（基线同样失败）：
  `test_image_directory_picker_opens_right_drawer_with_three_column_masonry`（路径超 260）、
  `test_festival_id_guard_survives_optimize` 与
  `test_real_second_process_refused_on_overlay_topology`（子进程输出按 cp1252 解码）、
  `test_capture_window_rect_coordinates_and_clamping`（多显示器负原点）。
- 1 个是 `test_modern_settings_dialog_py_line_budget`，即上表「架构红线」那一条，已校准。

**这次全量跑在最后三处改动之前**，没有在最终的文件树上重跑：toolset 上的缓存断点
（`_open_stream` 1 行 + 对应断言）、行数预算校准（测试常量）、本报告与索引登记。
这三处之后只重跑了相关文件：`tests/test_architecture.py tests/test_pr_report_discipline.py
tests/test_github_connector.py tests/test_anthropic_provider.py tests/test_desktop_pet_features.py`
→ `1 failed, 243 passed`，失败的是上面的路径超 260 基线项。**后续**：§九 的全量运行覆盖了这三处改动（4 failed 均为基线，4905 passed）。

## 七、已知限制与后续

- **只读、只有 GitHub**。没有写操作，也没有确认界面；要开放写工具必须先有「执行前
  确认」的交互，本次不做。Google Drive / Slack 需要各自注册 OAuth 应用，本次不做。
- **工具集固定**为 GitHub MCP 的默认只读集合（仓库、Issue、PR、用户等），不能在设置里
  裁剪。裁到只剩仓库（`/x/repos/readonly`）可把工具定义减到约一半，代价是查不了
  Issue / PR；有缓存后差别约 $0.001/条，没有做成设置项。
- **等待工具时界面没有进度提示**：模型调用工具期间流里没有文字，首段文字到达前聊天窗
  没有任何变化（两例实测 6.9 s / 8.4 s）。流里有 `mcp_tool_use` 事件，可以据此显示
  「正在查 GitHub…」，本次未做。
- **`pause_turn` 续跑没有实机样本**（15 次成功的真实请求都没触发）。
- **工具调用不进聊天记录**：会话里只存最终文字。下一轮对话模型看不到上一轮的工具
  结果，需要时会重新查。
- **MCP connector 是 beta 功能**（`mcp-client-2025-11-20`）。接口变更时这里会直接 400，
  届时关掉开关即可恢复普通对话。
- **Token 经过 Anthropic**：每次请求都把 PAT 发给 Anthropic，由它去连 GitHub。classic
  PAT 的权限范围是整个账号；地址上的 `/readonly` 限制的是 MCP 服务器暴露的工具，不是
  Token 本身。建议换成只读的 fine-grained PAT（是否被该 MCP 服务器接受未测）。

## 八、风险与回滚

- **影响面**：开关默认关；关着时请求与改动前相同。开着时影响三个交互式对话入口。
- **新增配置键**：`chat.github_connector`（布尔）。旧版本读到会忽略；旧版本一旦保存聊天
  设置，这个键会被丢掉（升级回来后是默认的关）。
- **新增钥匙串条目**：`dsh-pet-standalone` 服务下的 `connector/github`。
- **回滚**：`git revert` 后配置里残留 `chat.github_connector`，无害；钥匙串里的 Token
  不会被自动删除，需要在 Windows 凭据管理器里手动删掉 `connector/github`，并建议到
  GitHub 撤销该 PAT。

---

## 九、第二轮：「关于我」设置（同日追加，基线 `6e142a4`）

### 核心特性

连接器让桌宠**能**查 GitHub，但它不知道该查哪个仓库：问「我最近最需要盯紧的一件事是
什么」，回答是「能告诉我是哪个仓库/组织吗」。用户的个人知识库在私有仓库
`<owner>/<知识库仓库>`（约 540 KB Markdown，根目录 `INDEX.md` 是地图），整库放进提示词
不现实。新增设置「关于我」：一段用户自己写的说明（是谁、资料在哪），对话时追加在人设
后面，桌宠据此按需去读。

**为什么不直接写进 System Prompt。** `PromptBuilder.effective_system_prompt` 的人设是
三选一：调用方给的 > 角色包 `manifest.json` 里的 `chat.system_prompt` > 设置页的
System Prompt，前者存在时后者**整段不用**。当前两个内置角色（`claude`、`shenshen`）都
没有自带人设，所以设置页那段现在是生效的；但只要换上一个自带人设的角色包，写在里面的
知识库指引就会跟着消失。「关于我」不属于人设，三种来源下都追加。

**不变量**：「关于我」为空（默认）时，发出的消息与改动前逐字相同
（`test_blank_about_user_leaves_the_prompt_untouched`）；`effective_system_prompt` 的
返回值不变，文件解读、会话建档等直接用它的地方不受影响
（`test_the_persona_itself_does_not_include_about_user`）。

### 修改文件说明

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/chat/prompt.py` | +6 / −1 | `build_messages`：取到人设后，`settings.about_user` 非空则以空行隔开追加。只改这一处——三个交互式对话入口都经它组消息；文件解读走 `effective_system_prompt`，不带工具，不追加 |
| `pet/chat/models.py` | +5 / −2 | `ChatSettings.about_user`（默认空串，读写 `chat.about_user`，读入时去首尾空白） |
| `pet/chat/ai_settings_page.py` | +8 / −0 | 「模型与连接」分组里 System Prompt 下方新增一行多行输入框 `about_user`；保存时写回 |
| `pet/modern_settings_dialog.py` | +1 / −0 | 分组登记 1 行 |
| `tests/test_architecture.py` | +2 / −1 | `modern_settings_dialog.py` 行数预算 2396 → 2397，理由同上一轮（只多 1 行登记） |
| `tests/test_about_user_prompt.py`（新增） | +141 / −0 | 8 条：三种人设来源下都追加、空值不改消息、人设本身不含它、持久化、设置页编辑与回显、聊天窗发出的 system 消息以它结尾 |

设置准入记录：`about_user`，域 / 组「AI 与对话 / 模型与连接」，默认空，`primary`，无依赖，
随设置窗保存（`on_finish`），新键 `chat.about_user`、无旧键，清空即恢复原行为。

### 性能分析

方法同 §四（真实配置副本、真实 Key 与 Token、`claude-sonnet-5`），消息由
`PromptBuilder.build_messages` 从配置生成；「关于我」为 162 字。

| 指标 | 实测 | 归属 |
|---|---|---|
| system 消息长度 | 431 → 595 字符 | 新增 |
| 闲聊一条的未命中缓存 token（`cache_write`），无 / 有「关于我」 | 594 / 739（+145，n=1） | 新增 |
| 闲聊首段文字，有「关于我」（n=1） | 3.1 s，未调用工具 | 与 §四 连接器开时的 3.4–3.9 s 同量级 |
| 个人问题（读 `INDEX.md`，1 次工具调用，n=1） | 首段文字 5.1 s，总计 7.0 s；`cache_write 16342 / cache_read 12474`，输出 199 | 新增 |
| 个人问题（读 3 个文件，n=1，指引文字相同、经环境变量注入） | 首段文字 10.1 s，总计 14.0 s；`cache_write 7829 / cache_read 57457`，输出 693 | 新增 |
| 新测试文件 | 8 条（与相关文件合计 358 条共 18.0 s） | — |

结论：① 「关于我」为空时没有任何变化；② 非空时每条消息多出这段文字的 token（本例约
145），并且**它会让桌宠在个人问题上主动读仓库**——成本主要来自被读文件的内容，上表两例
输入合计约 2.9 万 / 6.5 万 token（大部分走缓存读），随问题而变；③ 没有新的系统调用、
网络目的地、磁盘或线程；④ 没有新增缓存或常驻对象。样本都是 n=1，只说明量级。

### 实机运行记录

```text
before: about chars 0 | connector True
after: about chars 162 | connector True | persona chars 431      ← 写入真实 config.json 的 chat.about_user
2026-10-11 21:27:04 acquired pid=55396 …                         ← 桌宠用新代码重启
```

```text
system chars: 595 | ends with about: True
问：我最近最需要盯紧的一件事是什么？一句话。
答：（回答内容来自用户的私人笔记，此处从略；与笔记里的记录一致）
-- stop_reason end_turn | blocks ['mcp_tool_use', 'mcp_tool_result', 'text']

system chars: 431 | ends with about: False          ← 同一问题，去掉「关于我」
答：嗯……这个问题我得先知道盯哪儿呀~ 我没有你具体要关注的 GitHub 仓库或项目信息，能告诉我是哪个仓库/组织吗？
-- stop_reason end_turn | blocks ['thinking', 'text']

问：给我讲个冷笑话。                                 ← 有「关于我」的闲聊
-- stop_reason end_turn | blocks ['thinking', 'text']   ← 没有去读仓库
```

**答案里暴露的现实问题**：回答里引用的那个日期是仓库里 9 月的记录，今天是 10 月 11 日。
GitHub 上的 知识库仓库 最后一次提交是 2026-10-04，本地知识库（Google Drive 上的 Obsidian
库，不是 git 工作区）在那之后的内容桌宠读不到——另一次实测问到个人项目时漏掉了
10 月 9 日才加的那个项目。同步由用户自行处理，不在本改动范围内。

设置页：真实 Windows 窗口截图 2 张（宽 1100 / 720），新行在 System Prompt 与连接测试
之间，无裁切，横向滚动条最大值 0。截图未入库。

**没有自动验证的部分**：仍然没有在真实聊天窗里打字提问（理由同 §五）。实测期间用户有
一个 21:17 打开的设置窗口（旧代码的独立进程）没有关；在那个窗口里点保存会用旧快照
覆盖聊天设置并丢掉 `chat.about_user`，已告知用户关掉重开。

### 测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests scripts`、`git diff --check` | 通过 |
| 红 → 绿 | `pytest -q tests/test_about_user_prompt.py` | 改动前 5 failed / 3 passed（通过的 3 条是「不变」类断言）；改动后 8 passed |
| 聚焦 + 相关 | 上一轮的文件集 + `tests/test_about_user_prompt.py tests/test_architecture.py tests/test_desktop_pet_features.py` | 356 passed, 1 skipped, 1 failed（路径超 260 的基线项） |
| 受影响时序族满载 3 遍 | — | 不适用：新测试全部同步断言 |
| 全量 | 同 §六 的命令，在包含两轮全部代码改动的文件树上 | `4 failed, 4905 passed, 11 skipped in 395.32s`；4 个失败就是 §六 列出的本机环境性基线项，没有其它失败。这次运行之后只改了本报告与索引（`tests/test_pr_report_discipline.py` 单独重跑通过） |

### 已知限制

- 「关于我」是提示，不是权限：里面写「不要读取凭据」拦不住模型去读仓库里的登录笔记
  （知识库的 GitHub 副本里有登录类笔记）。用户已知并选择保持现状。
- 指引让桌宠在个人问题上多一次到几次工具调用，回答会比闲聊慢 2–10 秒。
- 只作用于三个交互式对话入口；主动识屏、文件解读不带这段。

---

## 十、第三轮：本地知识库（同日追加，基线 `cef002e`）

### 核心特性

前两轮让桌宠经 GitHub 连接器去读知识库仓库，可用但每次都绕远：每条消息带约 1.23 万
token 的 GitHub 工具定义，读一个文件要 Anthropic 服务器 → GitHub MCP 服务器走一趟。
本轮新增「本地知识库」：把一个 GitHub 仓库每天同步成本机副本，对话时桌宠用三个本地
工具只读这份副本。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 同步 | 下载仓库默认分支的 zip 包并解压，只留文本文件；整目录原子替换，失败保留旧副本 |
| 2 | 每日自动 | 主进程里的定时器每 10 分钟看一眼是否到期（没有副本 / 换了仓库 / 超过 24 小时）；失败后 30 分钟内不重试 |
| 3 | 本地工具 | `kb_read` / `kb_list` / `kb_search`，路径限制在副本目录内 |
| 4 | 工具循环 | Claude 通道第一次有了客户端工具：模型要调用时在聊天工作线程里执行，结果接回去再请求 |
| 5 | 设置 | 「AI 与对话 → 知识库」：开关、仓库、立即同步（带状态文字） |

**与用户原话的两处差异（实现者的判断）**：用户说的是「每天 clone」。实现为下载 zip：
不要求本机装 git，Token 只出现在 HTTPS 请求头里（不进进程命令行、不进 `.git/config`），
也不新增子进程。副本里只留 `.md .markdown .txt .rst .org .csv .json .yaml .yml`，
跳过图片、点开头的目录和文件（`.obsidian` 等）与单个超过 2 MB 的文件。

**红线 / 不变量**

- 开关关闭（默认）时请求与改动前相同：`toolset_for` 返回 `None`，`_open_stream` 不加
  任何字段（上一轮的 `test_requests_without_connectors_are_unchanged` 仍然通过）。
- 读取不出副本目录：`../`、绝对路径、盘符路径一律拒绝
  （`test_reads_stay_inside_the_copy`）；zip 条目同样不能写到副本目录之外
  （`test_archive_entries_cannot_escape_the_copy`）。
- Token 不落盘：`state.json` 里没有它（`test_sync_keeps_text_files_only_and_records_the_state`）；
  `ProviderConfig.client_tools` 是运行期字段，不进 `to_dict()`。
- 工具出错不等于请求失败：错误以 `is_error` 回给模型，聊天线程不死。

### 修改文件说明

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/chat/knowledge_base.py`（新增） | +370 / −0 | 不依赖 Qt 的全部逻辑。`parse_repo`（`owner/repo`、网址、克隆地址都认）；`sync`（下载 → 安全解压到 `incoming-<pid>` → `os.replace` 换成 `current` → 写 `state.json`；失败把原因记进状态并保留旧副本）；`needs_sync` / `has_copy` / `describe`；`KnowledgeBase`（list / read / search，路径沙箱，长文件截到 4 万字）；`KnowledgeToolset`（三个工具的定义、用法说明、执行入口）；`toolset_for`（开关开、Claude 通道、本地有该仓库副本才返回） |
| `pet/chat/knowledge_sync.py`（新增） | +113 / −0 | `KnowledgeBaseSync(QObject)`：定时检查，到期在 daemon 线程里同步，结果经信号排队回 GUI 线程；结构照 `api_key_monitor.py`。每次检查重新读配置，所以不需要「设置改了」的通知 |
| `pet/chat/anthropic_provider.py` | +48 / −7 | `_open_stream` 接受 `client_tools`，把定义并入 `tools`（可与 MCP toolset 并存）；只要带了工具就开顶层自动缓存。`stream` 的循环从「只续 `pause_turn`」扩成两种续跑：`pause_turn`（上限 4）与 `tool_use`（上限 8 轮）。新增 `_run_client_tools`：一轮内所有工具结果放进同一条 user 消息。工具的用法说明追加到 system 末尾 |
| `pet/chat/models.py` | +11 / −3 | `ChatSettings.knowledge_base_enabled` / `knowledge_base_repo`；`ProviderConfig.client_tools`（运行期；`to_dict` 在 `asdict` 深拷贝前先摘掉它） |
| `pet/config.py` | +6 / −0 | `Config.resolve_client_tools(provider)` |
| `pet/chat/widgets.py`、`legacy_widgets.py`、`pet/quick_chat.py` | 各 +1 / −0 | 发送前填 `config.client_tools` |
| `pet/chat/ai_settings_page.py` | +81 / −7 | 「知识库」分组三行与「立即同步」（daemon 线程 + `_safe_emit` 回信号，同「测试连接」的做法）。GitHub Token 行改为连接器或知识库任一打开就显示（私有仓库同步要它），说明文字相应改写 |
| `pet/app.py` | +13 / −0 | `AppShell.start()` 里调 `_start_knowledge_sync()`：创建并启动定时器；无聊天打包变体跳过，异常不阻断启动 |
| `pet/modern_settings_dialog.py` | +1 / −0 | 分组登记 1 行 |
| `tests/test_architecture.py` | +2 / −1 | `modern_settings_dialog.py` 行数预算 2397 → 2398，理由同前两轮 |
| `tests/test_knowledge_base.py`（新增） | +617 / −0 | 43 条：仓库名解析 9、同步 11（内容筛选、无 Token、路径逃逸、整目录替换、5 种失败、私有仓库提示、到期与退避）、本地读取 6、挂载条件与持久化 2、工具循环 6（执行并回填、工具出错、轮数上限、取消、与连接器并存、真 SDK 接口）、配置与三个对话入口 4、设置页 2、每日同步 3 |

**先写了实现的那一部分**：`knowledge_base.py` 的纯逻辑是先写的，对应 29 条测试第一次
运行就是绿的，没有「先红」的记录。其余 14 条（工具循环、配置接线、对话入口、设置页、
每日同步）在实现前运行为红。

**未改动**：`pet/chat/connectors.py`（GitHub 连接器原样保留，两者可同时开）；
OpenAI 兼容通道（`providers.py`）没有工具循环，知识库在那里不生效。

### 实现要点

**为什么工具循环是手写的。** SDK 有现成的 tool runner，但这里要同时满足：逐段把文字
交给界面、随时可取消、与服务端的 MCP 连接器共存、续跑 `pause_turn`。这些在既有的流式
循环里加一个分支就够了，换成 runner 反而要绕开它。

**一轮的结构。** 流结束后看 `stop_reason`：`tool_use` → 逐个执行本轮的 `tool_use` 块 →
把 assistant 的整段 `content`（含 thinking 块，原样）和一条装着全部 `tool_result` 的 user
消息接到历史末尾 → 再请求。

**用法说明跟着工具走。** 「先读 INDEX.md」这段话在 `KnowledgeToolset.system_note` 里，
由 provider 在带工具时追加到 system。没有本地副本就没有工具，也就不会出现「叫模型去查
一个不存在的东西」。上一轮写进「关于我」的 GitHub 指引因此不再需要。

**说明文字的措辞是测出来的。** 第一版写「通常先读 INDEX.md」，同一个问题模型先搜了
三次中文关键词（笔记文件名是英文）才去读地图，共 6 次请求；改成「第一步用 kb_read 读
根目录的 INDEX.md……找不到再用 kb_search」后两次复测都是 4 次请求（见下表）。

**跨进程。** 设置窗口是独立进程，它的「立即同步」和主进程的定时同步写同一个目录：
临时目录按 pid 取名，替换是 `os.replace`，状态文件先写临时文件再替换；主进程每次发送
都重新读状态，不缓存。

**设置准入记录**

```text
setting_id            knowledge_base_enabled / knowledge_base_repo（knowledge_base_sync 是命令按钮，不存值）
domain_id / group_id  AI 与对话 / 知识库
default               关 / 空
capability            仅 Claude 通道生效（含经网关访问）；私有仓库依赖「连接器」分组里的 GitHub Token
disclosure_level      primary
dependency            仓库行、同步行依赖开关（关时隐藏）
commit_policy         on_finish；「立即同步」用表单里的当前值，不要求先保存
migration             新键 chat.knowledge_base_enabled / chat.knowledge_base_repo，无旧键
recovery              关掉开关即回到改动前；副本在 <配置目录>/knowledge-base/，可直接删除
```

「立即同步」是命令而不是偏好，按 [`SETTINGS-CHANGE-GATES.md`](SETTINGS-CHANGE-GATES.md)
本不该进设置页；放在这里是因为它是这组设置唯一的验证手段（仓库名、Token 填得对不对），
与同页既有的「测试连接」同类。

### 性能分析

**方法**：真实配置的副本 + 真实 Key 与 Token，`claude-sonnet-5`，effort `medium`；
消息由 `PromptBuilder.build_messages` 生成，经 `AnthropicProvider.stream`。同步用
`knowledge_base.sync` 的默认下载器直连 `api.github.com`。环境同 §四。

| 指标 | 实测 | 归属 |
|---|---|---|
| 同步 `<owner>/<知识库仓库>`（仓库 105 个文件） | 0.83 s，留下 71 个文件 / 520,891 字节 | 新增，每天 1 次 |
| 私有仓库不带 Token | 0.26 s 后失败：「找不到仓库……私有仓库需要先在「连接器」里填 GitHub Token」 | 新增 |
| `kb_read INDEX.md`（n=20） | 中位 0.21 ms，最大 6.00 ms | 新增 |
| `kb_search "<关键词>"`（71 个文件全扫，n=20） | 中位 8.04 ms，最大 732.84 ms（第一次，磁盘缓存是冷的） | 新增 |
| `kb_list` 根目录（n=20） | 中位 0.47 ms，最大 1.01 ms | 新增 |
| 闲聊一条，只开知识库（n=1） | 首段文字 3.1 s，1 次请求，未调用工具；输入 1,407 token（缓存写） | 新增 |
| 「最需要盯紧的一件事」，只开知识库（n=1） | 首段文字 **4.2 s**，总计 6.1 s，2 次请求，读 `INDEX.md`；两次请求输入合计约 6,600 token（其中 1,418 走缓存读） | 新增 |
| 同一问题，上一轮经 GitHub 连接器（n=1，§九） | 首段文字 5.1 s，总计 7.0 s；输入合计约 28,800 token | 对照 |
| 「某个个人项目做到哪一步」，第一版说明（n=1） | 首段文字 9.9 s，总计 13.9 s，**6 次请求**（先搜 3 次） | 已改掉的措辞 |
| 同一问题，现在的说明（n=2） | 首段文字 8.1 s / 6.1 s，总计 12.5 s / 10.3 s，**4 次请求** | 新增 |
| 知识库 + GitHub 连接器同开，一问两头（n=1） | 首段文字 10.5 s，总计 21.4 s，3 次请求；同一轮里本地 `tool_use` 与 `mcp_tool_use` 并存，都正确返回 | 新增 |
| 桌宠启动到自动同步完成 | 10 s（延时 8 s + 同步） | 新增 |
| 新测试文件 | 43 条 2.9 s | — |

**结论**

1. **稳态开销（开关关）**：每次发送多一次 `chat_settings()` 解析和一次布尔判断，不读
   磁盘、无网络。主进程多一个 10 分钟一次的定时器，关着时每次只解析一遍聊天配置。
2. **新增路径**：开着时每次发送读一次 `state.json`（没有单独计时；同目录下读 9 KB 的
   `INDEX.md` 中位 0.21 ms）。每条消息多三个工具定义加用法说明，共约 950 token（闲聊
   输入 1,407 对比连接器全关时的 455），是 GitHub 连接器（约 12,300）的十三分之一。
   个人问题每多读一步就多一次完整请求，首段文字因此比闲聊晚 1–5 s。
3. **新的系统调用 / 网络 / 磁盘 / 线程**：有，都是本轮引入的——
   网络：每天一次到 `api.github.com`（跳转 `codeload.github.com`）的 HTTPS 下载，走系统
   代理（按 [`NETWORK-PROXY-AND-VPN-2026-09-22.md`](NETWORK-PROXY-AND-VPN-2026-09-22.md)
   的约定，未特殊处理）。磁盘：`<配置目录>/knowledge-base/` 下一份副本（本例 0.5 MB）与
   `state.json`。线程：同步期间一个 daemon 线程。没有新的子进程。
4. **内存**：下载的 zip 整个读进内存后解压（上限 200 MB；本例解压出的文本共 0.5 MB，zip 大小没有单独记录），同步结束即
   释放；没有常驻缓存，副本内容每次从磁盘读。

样本量多为 n=1 或 2，只说明量级；没有做「知识库 vs 连接器」的多样本对照。

### 实机运行记录

**真实同步与本地读取**（临时配置目录，真实 Token）

```text
=== sync without token (private repo) ===
sync failed after 0.26s: 找不到仓库 <owner>/<知识库仓库>（私有仓库需要先在「连接器」里填 GitHub Token）
=== sync ===
synced in 0.83s: files=71 bytes=520891
describe: 上次同步 2026-10-11 21:49，71 个文件。之后每天自动同步一次。
top level: （12 个顶层条目，名称从略）
```

`.obsidian`、`.gitignore`、两个 `.bak` 都没有进副本。

**对话**（桌宠自己的代码路径）

```text
model=claude-sonnet-5 connector=[] kb_tools=True
问：我最近最需要盯紧的一件事是什么？一句话。
答：（回答内容来自用户的私人笔记，此处从略；与笔记里的记录一致）
-- first_text=4.2s total=6.1s requests=2
-- local tool calls: kb_read INDEX.md，随后按需 kb_list / kb_read 具体笔记（路径从略）
-- stop tool_use | in 2 out 53 cache_write 1418 cache_read 0 | blocks ['tool_use']
-- stop end_turn | in 2 out 85 cache_write 3769 cache_read 1418 | blocks ['text']
```

```text
问：（一个需要查知识库才能回答的个人问题，内容从略）
答：（回答内容来自用户的私人笔记，此处从略；与笔记里的记录一致）
-- local tool calls: kb_read INDEX.md，随后按需 kb_list / kb_read 具体笔记（路径从略）
-- requests=4，中间几轮的 blocks 含 'thinking'：带 thinking 块的内容原样回传被 API 接受
```

```text
问：（一个需要查知识库才能回答的个人问题，内容从略）另外 LiminCode/BigFatFish 最近一次提交是什么？   （知识库 + 连接器）
-- local tool calls: kb_read INDEX.md，随后按需 kb_list / kb_read 具体笔记（路径从略）
-- stop tool_use | blocks ['thinking', 'tool_use', 'mcp_tool_use']          ← 同一轮里两种工具
-- stop tool_use | blocks ['mcp_tool_result', 'thinking', 'tool_use', 'tool_use', 'tool_use']
-- stop end_turn | blocks ['text']                                          ← 两个问题都答了，提交信息与 §五 一致
```

**真实桌宠**

```text
before: kb False '' | about chars 164 | connector True
after: kb True '<owner>/<知识库仓库>' | about chars 0 | connector True
2026-10-11 21:51:15 acquired pid=37912 …
2026-10-11 21:51:25,112 INFO 知识库同步完成：<owner>/<知识库仓库>：71 个文件     ← 桌宠自己的日志：启动 10 s 后定时器自行同步
state.json: {"repo": "<owner>/<知识库仓库>", "synced_at": 1791780684.23, "files": 71, "bytes": 520891, …, "error": ""}
knowledge-base/: current, state.json                                       ← 没有残留的临时目录
```

**操作失误记录**：启用时把真实配置里的「关于我」清空了（它原本只有上一轮写入的 GitHub
指引，与本地知识库的用法说明冲突）。清空前只核对了长度：164 字，而上一轮写入的是 162
字——用户可能改过两个字符，改了什么没有留存，也没有备份可查。已告知用户并给出原文。

**设置页**：真实 Windows 窗口截图（宽 1100 / 720，开关开），见下「测试与验证」。

**没有自动验证的部分**

- 仍然没有在真实聊天窗里打字（理由同 §五）。
- **24 小时后的自动再同步**没有等到：只有替身时钟的测试（`test_daily_sync_runs_when_due…`）
  和「启动后首次同步」这一次真实观察。
- `AppShell.start()` 里的接线没有单元测试（启动整个壳太重），证据是上面那行真实日志。
- 同步期间断网、磁盘满、路径超长：只有替身覆盖（5 种失败的参数化用例），没有实机制造。

### 测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests scripts`、`git diff --check` | 通过 |
| 红 → 绿 | `pytest -q tests/test_knowledge_base.py` | 接线前 14 failed / 29 passed（见上「先写了实现的那一部分」）；完成后 43 passed |
| 聚焦 + 相关 | 本轮与前两轮的测试文件 + `test_anthropic_provider` `test_architecture` `test_chat_subsystem` `test_file_interpret` `test_config_domains` `test_config_key_migration` `test_desktop_pet_features` `test_api_key_monitor` | 全部通过，除路径超 260 的基线项 |
| 受影响时序族满载 3 遍 | `tests/test_knowledge_base.py` 里用到事件循环的 5 条（设置页同步 2、每日同步 3） | 3 遍均 `5 passed`（0.36–0.50 s）。当时全量套件在同一台机器上并行运行，没有另外把 CPU 打满 |
| 全量 | 同 §六 的命令 | `4 failed, 4948 passed, 11 skipped in 425.27s`；4 个失败是 §六 列出的本机环境性基线项，没有其它失败。这次运行之后只改了工具用法说明的一句措辞（没有测试断言这句话的具体文字，`tests/test_knowledge_base.py` 单独重跑 43 passed）以及本报告与索引 |
| 设置页截图 | 真实窗口，宽 1100 / 720 | 无裁切，横向滚动条最大值 0。第一次截图里仓库行的说明被截成一行，原因是截图脚本只处理了一轮事件、布局还没稳定；多处理几轮后该行说明高 32 px，等于所需的 32 px（两行）。截图未入库 |

### 已知限制与后续

- **GitHub 上的仓库旧，副本就旧。** 本例 GitHub 副本停在 2026-10-04，答案里引用的一个日期
  已经过期。用法说明提醒了模型「内容截至同步时间」，但它不知道仓库本身多旧。
- **只读默认分支**；不能选分支或子目录。
- **只有 Claude 通道**；OpenAI 兼容通道没有工具循环。
- **搜索是逐文件子串匹配**，不分词、没有索引。71 个文件 8 ms；上万个文件时要重做。
- **读文件时界面仍然没有进度提示**（同 §七）；现在一个问题可能是 2–4 次请求。
- **副本里有什么，模型就能读什么**，读到的内容随对话发给模型服务商。本例仓库里的
  登录类笔记也在副本里；用户已知并选择保持现状。
- 整包下载，没有增量；仓库超过 200 MB 直接拒绝。
- 可以直接把知识库指向一个本地文件夹（例如已经在本机的 Obsidian 库），读取部分不用改，
  本轮没有做这个入口。
