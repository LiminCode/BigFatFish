# PR 报告：小肥鱼标签最左边加「从哪开的」图标（VS Code / Claude 桌面版 / 终端 / WSL）

> **基线**：`ab6f4049`（`feature/session-fish-persist` 分支尖，PR #13；本 PR 叠在它上面，因为冻结鱼也要有图标）
> **分支**：`feature/fish-host-badge`　**日期**：2026-11-02
> **范围**：9 个文件（实现 5、测试 3、文档 1）
> **关联**：[`PR-REPORT-SESSION-FISH-PERSIST-2026-11-02.md`](PR-REPORT-SESSION-FISH-PERSIST-2026-11-02.md)（冻结鱼 / 入口字段）、
> [`PR-REPORT-CLAUDE-CODE-SESSION-FISH-2026-10-11.md`](PR-REPORT-CLAUDE-CODE-SESSION-FISH-2026-10-11.md)（标签胶囊、详情卡页头的程序图标）

## 一、核心特性

用户 2026-11-02：二十来只小肥鱼在场，**表面上看不出来源**——哪只是 VS Code 开的、哪只是 Claude 桌面版、哪只是终端 /
WSL；详情卡页头那块程序图标要搬到鱼头顶的文字旁边。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 图标放在胶囊**最左边** | 顺序：来源图标 → 桂冠（如果戴）→ 「名字 · 状态」。来源是「这只鱼是谁」，放在最前；桂冠是「跑的什么模型」，其次 |
| 2 | 与详情卡同一份图标 | `host_icons`：本机装着的那个程序自己的图标（VS Code 的 `Code.exe`、商店版 Claude 桌面版、PowerShell、`wsl.exe` 的企鹅）；没装的、`sdk-cli` 的脚本会话用手绘单色记号，**记号颜色跟胶囊字色**（深底白字、淡绿底墨绿字、天蓝底深蓝字都看得清） |
| 3 | 规则与详情卡同一份 | `claude_session_info.host_kind(entrypoint, wsl)`：`claude-vscode` → VS Code（WSL 里的 VS Code 也是）、`claude-desktop` → 桌面版、WSL 通道的其余会话 → 企鹅、本机 `cli` → PowerShell、`sdk-cli` → 脚本记号；入口还不知道（hook 事件先到、运行清单还没补上）就先不画，清单补上入口后那一帧就有 |
| 4 | 冻结鱼也有 | 历史行里记着入口（`entry.host`，PR #13 加的字段），灰胶囊左边同样一枚 |
| 5 | 不动布局 | 图标占 18 px（14 px 图 + 间距），胶囊按此加宽，文字不被压；胶囊仍钳在 sprite 画布矩形里（省略规则不变：先省名字、状态词完整） |

## 二、修改文件说明

| 文件 | 改了什么 | 为什么 |
|---|---|---|
| `pet/pet_sprite.py` | `caption_host`；`_CAPTION_HOST_W / _CAPTION_HOST_PX`；`_caption_lead_width()`（来源 + 桂冠）；排版与贴图缓存键带上来源；`_paint_host`（`QIcon.paint` 进胶囊） | 标签胶囊是 sprite 自己画的，图标要进同一张缓存贴图，每帧仍是一次 `drawPixmap` |
| `pet/host_icons.py` | `host_icon(..., ink=)`：手绘记号按颜色各缓存一份，真图标仍只按 (种类, 尺寸, DPR) 缓存一份；`probe_widget(dpr)` + `host_icon_for_dpr()`；`clear_cache` 连探针一起清 | sprite 手里没有 widget，只有所在屏的 DPR；胶囊有深有浅，单色记号得跟字色 |
| `pet/overlay_shell.py` | `set_session_pet_caption(..., host=)`，变了才重绘 | 壳是标签的唯一写入口 |
| `pet/overlay_session_pets.py` | `_host_for(key)`（入口 + 是否 WSL 通道 → 种类）；活鱼每次更新、`remodel`、`refresh_badges`、冻结鱼出场都把来源带上 | 来源与状态 / 桂冠一起下发，换阶段、换模型不丢 |
| `pet/session_pet_ui.py` | 启动预热多热一份：胶囊尺寸（14 px、合成窗所在屏的 DPR） | VS Code 的图标第一次要外壳解包 ~200 ms（下面实测），别卡在第一只 VS Code 的鱼出场那一帧 |
| `tests/test_sprite_caption.py` | 3 条：图标在最左、桂冠其次、胶囊按格加宽且仍在画布内；不认识的来源不加宽；手绘记号跟字色（深底 / 淡绿底各一次） | sprite 画法 |
| `tests/test_overlay_session_pets.py` | 2 条：四种入口 / 通道 → 四种图标，入口晚到补上、换阶段与戴桂冠不丢；冻结鱼按历史行的入口 | 控制器接线 |
| `tests/test_host_icons.py` | 2 条：记号按颜色各缓存、真图标与颜色无关只取一次；按 DPR 不用 widget 取图（2.0 → 28 px 物理） | `host_icons` 的新接口 |

### 未改动

详情卡（它早就有这个图标）、菜单、设置、`host_kind` 的判定规则、历史行格式。

## 三、实现要点

- **测试里不依赖这台机器装了什么**：`_no_programs` fixture 把 `host_executable` 换成「都没装」，一律走手绘记号；
  真图标那条路由 `test_host_icons` 用替身 provider 测。
- **缓存两层**：`host_icons._CACHE` 按 (种类, 尺寸, DPR[, 颜色]) 存 `QIcon`；sprite 的胶囊贴图按 (文本, 尺寸, DPR, 配色,
  桂冠, 来源) 存 `QPixmap`。每帧只贴图；换文字 / 状态时重画一次胶囊，图标那一步是缓存里的 `QIcon.paint`。
- **探针 widget**：`probe_widget(dpr)` 是一个只报固定 DPR 的隐藏 `QWidget`（每种 DPR 一个，放模块字典里），
  `host_icon` 里 `devicePixelRatioF()` / `fitted_application_icon` / `_new_icon_canvas` 都是从 Python 调它，覆盖生效。
- **来源判定放控制器**：`_host_for(key)` 读 `_extras[key]["entrypoint"]`（hook 事件 / 运行清单 `note_registry` 补的）
  和 `key[0] == "claude_wsl"`；冻结鱼直接用历史行的 `entry.host`。两边都是 `host_kind`，与详情卡页头永远一致。

## 四、性能分析

本机（Windows 11，.venv Python 3.13，`QT_QPA_PLATFORM=windows`，`scratchpad/hostbadge_bench.py`）：

| 路径 | 实测 | 说明 |
|---|---|---|
| 第一次取 VS Code 图标 | **256 ms**（离屏 195 ms） | 外壳解包 `Code.exe`；与详情卡那次同一笔开销（2026-10-14 实测 150 ms），现在在启动预热里做（延迟定时器，不在生鱼路径上） |
| 第一次取桌面版 / PowerShell / wsl.exe 图标 | 9.1 / 6.4 / 8.6 ms | 同样预热掉 |
| 手绘记号 | 0.2 ms | 矢量画一次 |
| 胶囊重画（图标已缓存） | 无图标 0.06 ms / VS Code 0.09 ms / 企鹅 0.08 ms | `timeit` 200 次均值；每次换文字 / 状态一次 |
| 每帧（缓存命中） | **0.008 ms** | `caption_pixmap()` 2000 次均值；与改前同一条路径（只多比一个字符串键） |

- 稳态开销：每帧多比较缓存键里的一个字符串；没有新线程、定时器、系统调用、磁盘 / 网络访问（外壳取图只在预热那一次）。
- 新增路径成本与触发频率：胶囊重画 +0.02–0.03 ms，触发于状态 / 文字 / 来源变化，一只鱼一天几十次。
- 内存：`host_icons._CACHE` 多出胶囊尺寸的一组图标（每种来源一个 14 px `QIcon`，14×14×DPR² ×4 B，共 < 20 KB）；
  每种 DPR 一个隐藏探针 widget（实机 2 种 DPR）。

## 五、实机运行记录

1. **测试**：7 条新测试先红（`caption_host` 不存在 / `host_icon` 不收 `ink` / 没有 `host_icon_for_dpr`）后绿；相关族
   （标签胶囊 / 来源图标 / 会话小鱼 / 桂冠 / 详情卡 / sprite / 护驾 / 壳宿主）**176 passed**；`ruff check pet/ tests/` 过。
2. **真图标渲染样图**（本机，`QT_QPA_PLATFORM=windows`，2 倍 DPR 离屏画到 PNG，已发给用户）：五条胶囊——VS Code + 桂冠的
   淡绿「工作中」、Claude 桌面版的天蓝「等你回复」、PowerShell 深灰「休息中」、企鹅深灰「等你批准」、VS Code 灰「冻结」；
   四种程序图标都取到了本尊（`host_executable` 全命中），字不被压，胶囊圆角完整。离屏平台（`offscreen`）下外壳只给通用文档
   图标且没有中文字形——那张不作数，测试也因此一律走手绘记号。
3. **实机**：见文末「实机补记」。

### 实机补记（2026-11-02 21:14）

提交 `a37aaef5` cherry-pick 到本地运行分支（`local/run-with-toast-fix`；只有 `docs/INDEX.md` 两行索引并排冲突，两行都留），
重启桌宠（pid 49616）：启动日志 **0 ERROR / 0 WARNING**；从运行清单认领 19 个会话、19 只活鱼出场（认领时入口随清单一起到，
图标第一帧就有），先出场的 19 只冻结鱼让掉 18 只，最后 19 活 + 1 冻结 = 20（上限）。标签左边的图标在屏上长什么样、
hook 事件先到的新会话图标有没有在认领周期内补上，请用户看一眼回报（我没法截合成窗；真图标的离屏样图见记录 2）。

**用户回报（2026-11-02 21:20）**：看了屏上的鱼，「对，没问题」——图标位置与四种来源都对。

## 六、已知限制与后续

- 入口来自 Claude Code 自己的运行清单 / transcript：hook 事件先到、清单还没扫到的那几秒没有图标（`_ADOPT_PERIOD_S` 内补上）。
- 手动生的小肥鱼、非会话鱼没有来源，不画。
- 非 Windows 平台一律手绘记号（`host_icons` 既有行为）。

## 七、风险与回滚

- 只给标签胶囊多画一格、`set_session_pet_caption` 多一个缺省参数；回滚 = revert 这一个提交。

## 数字

| 文件 | +/− |
|---|---|
| `pet/host_icons.py` | 37 / 6 |
| `pet/pet_sprite.py` | 31 / 6 |
| `pet/overlay_session_pets.py` | 12 / 4 |
| `pet/session_pet_ui.py` | 7 / 0 |
| `pet/overlay_shell.py` | 4 / 2 |
| `tests/test_sprite_caption.py` | 74 / 1 |
| `tests/test_host_icons.py` | 30 / 0 |
| `tests/test_overlay_session_pets.py` | 29 / 0 |

按 AGENTS.md 的风险门只跑焦点 + 相关族（局部绘制 + 一个缺省参数，接口、持久数据、生命周期、平台分派都没动），没重跑全量。
