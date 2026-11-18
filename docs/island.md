# 灵动岛

> 屏幕上一枚置顶的胶囊（头像、名字、今日用量、会话计数、连接图标、简报 / 个人助理 / 铃铛），点开是一张卡片：
> 「消息记录」和「最近的对话」两个折叠框加按钮。可拖到任意位置（包括盖在任务栏上），拖到屏幕边缘收成细条。

## 模块

| 文件 | 职责 |
|---|---|
| `pet/dynamic_island.py` | 岛本体：胶囊 / 卡片绘制、夹屏、停靠、展开收起动画、置顶保活、Metro 磁贴、命中测试 |
| `pet/platform_win.py`（「置顶看门狗」一节） | `occluder_above`（z 序里谁压着岛）、`topmost_hold_off`（真全屏 / 系统外壳在前台） |
| `pet/island_history_panel.py` | 「最近的对话」折叠框：行卡片、置顶图钉、右键菜单、`style_island_menu`、行数预算 |
| `pet/island_message_panel.py` | 「消息记录」折叠框（与上一个是孪生类，接口一致） |
| `pet/claude_session_history.py` / `pet/session_history_service.py` | 「最近的对话」的数据与落盘（`claude-session-history.json`）、置顶、过期与上限 |
| `pet/message_log.py` | 消息记录的数据与落盘（`message-log.json`）：去重、未读水位 |
| `pet/host_icons.py` | 来源图标：从本机程序取真图标，取不到退回手绘记号 |
| `pet/claude_usage.py` / `pet/claude_week.py` | 今日 / 近 7 天用量统计（零 Qt）：多根、分账号、WSL 根的发现、文案拼装 |
| `pet/claude_usage_monitor.py` | 后台线程里每分钟统计一次，发 `usage_changed(文案, 悬停说明, 分段)` |
| `pet/usage_dashboard.py` / `pet/usage_dashboard_ui.py` | 近 7 天仪表盘：磁贴数据与窗口（透明底、阴影、光晕文字） |
| `pet/api_key_monitor.py` | 体检聊天**在用**的那个模型服务，结论给连接图标 |
| `pet/island_connections.py` / `pet/island_connections_ui.py` | 「模型连接」面板：全部服务的状态、按需体检与缓存 |
| `pet/settings_island_icon.py` / `pet/settings_island_name.py` | 设置页里岛的「图标」「名字」两行 |
| `pet/app.py`（`AppShell`） | 接线：把历史 / 消息 / 用量 / 体检结论推给岛，处理岛发回的点击与菜单动作 |

## 机制与不变量

### 夹屏、停靠、展开方向

用哪块矩形是按场合定的，不要统一成一个：

| 场合 | 参照 | 原因 |
|---|---|---|
| 胶囊夹屏（拖拽松手、心跳、动画目标） | 整块物理屏 `screen.geometry()`（`_placement_bounds`） | 岛可以整个盖在任务栏上 |
| 展开且卡片在胶囊下方 | 工作区 `availableGeometry()`（`_clamp_bounds`） | 卡片是阅读面，不盖任务栏 |
| 展开且卡片在胶囊上方 | 整块物理屏 | 胶囊留在任务栏上，卡片在它上面、自然落在工作区里 |
| 停靠判定、细条位置、默认落点、卡片高度预算 | 工作区 | 细条贴的是屏幕边缘；没存过位置时落在工作区右上角 |

- **停靠只认「工作区边与物理屏边重合」的边。** `dockable_edges(available, screen_rect)`：某边工作区比物理屏内缩
  ≥ `_PANEL_MIN_INSET`（8 px）就是被任务栏 / 系统面板占住，不参与就近判定。过滤在取最近边**之前**做，
  所以岛贴着任务栏又靠右角时落到 `right`，而不是整体判 `none`。拿不到物理屏几何时四边都算。
  判据是两块几何的差，不是平台 API——任务栏在哪一边、macOS 菜单栏、第三方 Dock 都一样处理。
- **存着的停靠边在 `_apply_position` 自愈**（启动与 `refresh_from_config` 的共同入口）：落在被占的边上就写回
  `none` 并把细条形态复位。`dock_edge` 属性本身不能查 QScreen——它在绘制 / 碰撞路径里被高频读取。
- **展开方向只在展开那一刻定**（`_prefers_card_above`）：比较向下（按工作区夹）与向上（按物理屏夹）两种放法
  各要把胶囊挪多远，挪得少的赢，相同取向下；停靠态走 `_target_rect` 的停靠分支。卡片在上时胶囊画在窗口
  底部 44 px（`_capsule_top`），命中测试与悬停都先经 `_capsule_point` 换到胶囊坐标，窗口尺寸变化锚定胶囊
  底边（`_anchored_rect`）；`_card_is_above` 要到收起动画走完才失效。拖拽偏移 `_drag_offset` 按**胶囊**左上角
  算——按窗口左上角算的话，卡片在上时起拖会让胶囊跳一个卡片高。
- **收起回到展开前的位置**（`_rest_anchor`）：只在 `expand_card`（normal → expanded）写入，`collapse_card`
  读出即清空，卡片开着时 `_apply_position` 用设置里的新位置覆盖它。不要把它塞进 `_target_rect`——那个函数
  的语义是「当前模式、当前位置的目标矩形」，动画收尾、`showEvent`、停靠切换都在调，塞进去会把刚拖完的
  胶囊拽回旧位置。`_finish_animations` 必须先跳到 `_geo_to` 再按模式重算。
- **展开 / 收起动画只动画面不动窗口**（`_animate_to(target, reveal=True)`）：窗口一次摆到两头矩形的并集，
  180 ms 内只改 `_reveal_rect` 和 `_card_box` 的遮罩（`_sync_reveal_mask`，第一帧前就要遮上）。不要逐帧
  `setGeometry`：半透明层叠窗口改几何后 DWM 会先拿旧位图在新位置合成一帧，向上展开时胶囊就在原地上下跳。
  动画进行中 `_update_size` 只改 `_geo_to`——展开会触发 `card_expanded`，`AppShell` 回推数据走 `_refresh`，
  直落终点尺寸就是整块卡片闪一帧。停靠细条的滑出 / 收回仍是真几何插值。

### 卡片高度与行数预算

`_fit_card_to_screen`：预算 = 工作区高度 − 上下各 `_CARD_SCREEN_MARGIN`（16）− 胶囊 44。超出多少，就从
「行数 × `ROW_HEIGHT`」更大的那个折叠框一行一行拿（消息行 58、历史行 40），各自最少 `_CARD_FIT_MIN_ROWS`（2）行，
多出的行在框里滚动；两框都到 2 行还放不下（工作区不到约 480 高）只能顶到顶边、底部被截。

- 预算（`set_row_budget`）与用户配置的行数（`set_max_visible`，来自 `agent_link.session_history_rows`）**分开存**，
  `row_cap()` 取小；放得下的屏预算撤成 `None`。合成一个值的话，在矮屏压过一次，换到高屏行数回不来。
- 用整数算术一次算出各框行数，不逐步重排：面板每改一次预算要重填全部行（50 行约 8.5 ms），预算不变时
  整个拟合只有几微秒。折着的框不占高度也不参与。
- 重算点：`expand_card`、`_update_size`（`_refresh` 的所有来路：框开合、数据推送、30 s 心跳）、
  `_apply_position` 挪完之后再算一次（开头那次用的是旧位置所在的屏）。

### 置顶保活

岛是 `WS_EX_TOPMOST` + `WS_EX_NOACTIVATE`：从不被激活，而 topmost 带内的先后由「谁最近被激活」决定，
Windows 又不通知「你被盖住了」，所以岛要自己重申。唯一入口是 `reassert_topmost`，下列情况返回 False 不动：

- 岛隐藏；
- 本进程有 Popup 开着（`QApplication.activePopupWidget()`，即岛上列表的右键菜单）——否则弹菜单引发的
  焦点 / 前台两次重申会把岛插回菜单之上，挡住菜单；
- 本进程有带 `coversIsland` 属性的可见窗（仪表盘、模型连接面板：说好了要盖在岛上）。

触发点：`showEvent`、本进程窗口获得焦点、点岛、`_refresh` 心跳，外加 2 s 一轮的看门狗 `_watch_topmost`
（可见时才跑）。看门狗**真被盖住才插**：`occluder_above` 沿 z 序往上找与岛相交、可见、未被 DWM cloaked、
且属于**别的进程**的窗；找不到就一次 `SetWindowPos` 都不发。真全屏（QUNS 3 / 4）或系统外壳的面在前台时
（`topmost_hold_off`，类名表 `_SHELL_SURFACE_CLASSES`）歇着，所以点任务栏时任务栏在上，焦点离开后岛回来。

- **自家窗口不算盖住**：通知卡片有自己无条件的 2 s 看门狗，岛若也无条件插，两边会轮流把对方压下去。
- `platform_win` 里自备一份 `ctypes.WinDLL("user32")`：进程共享的 `windll.user32` 改了 `restype` 会影响别处
  按 int 用它的代码，而 64 位下 HWND 按 int 收会截断。

### 「最近的对话」

- 历史文件只存路径、标题、入口这类信息，**不存对话内容**（测试有字段白名单）。标题 / 路径按纯文本显示。
- **排序归数据层**：`_prune` 的排序键是 `(not pinned, -last_seen)`，界面只画不排。置顶的行不受
  `session_history_days` 过期；因为排在最前，`session_history_max` 切掉的总是队尾没置顶的。取消置顶立刻按原
  规则走。`set_pinned` 返回「有没有变化」，没变化不发信号、不落盘。旧文件没有 `pinned` 键 = 没置顶。
- 行首 16 px 来源图标（`HistoryEntry.host`：`vscode` / `desktop` / `terminal` / `wsl` / `script` / 空，WSL 里的
  VS Code 仍算 `vscode`）；不知道来源留空位，文字仍对齐。图标与手绘回退见 `host_icons.host_icon`，按
  （种类, 尺寸, 缩放）缓存，面板建好 2.5 s 后预热——VS Code 的图标首次要外壳解包约 150 ms，在 GUI 线程。
- 图钉用 `pin_pixmap` 按 accent 色自己画：`vector_widget_icon` 的颜色跟控件调色板走，而岛的文字色是配置定的。
- 行是「透明外框 + 卡片」两层：QSS 的 `margin` 对 QFrame 背景不生效，缝只能靠外框留。卡片底色按主文字色
  明暗取薄膜（`tile_colors`）：浅字 = 深底岛用白膜，深字用黑膜。
- 点一行 / 恢复会话见 [跳到对话](session-jump.md)；胶囊上的会话计数（`set_session_counts`）见 [会话小鱼](session-fish.md)。

### 「消息记录」

肥鱼头上冒过的通知气泡都留一笔：`message-log.json` 留最近 200 条，岛上只铺最近 50 条（200 行首次建控件
226 ms，50 行 12.5 ms）；铃铛 = 未读条数，打开框即看过（`seen_uid` 水位，跨重启）。

- **记在门禁之前**：`OverlayShell.show_bubble` / `show_alert` 第一行就经 `_note_message` 交给 `message_sink`，
  可见 / 抑制 / 飞行这些门禁都在后面——**记了 ≠ 弹了**，错过的气泡正是记录最有用的部分。记录抛错只写日志，
  气泡照出。肥鱼隐藏时改道到岛的气泡（`AppShell._island_feedback_bubble`）也记，靠 60 s 内「同会话同文案
  只记一次」（`DEDUP_S`）与前一笔合成一条。
- **不记**：自言自语、会话小鱼动作回执（它们不走这两个方法）；**过程汇报气泡**（「正在读文件…」）
  显式 `record=False`——每次工具调用一条，实机 2 分钟 4 条，不拦的话 200 条里只剩它们。
- **来源**是一个 `origin` 字典（`AgentLinkManager._bubble_origin`：通道 + 会话 id），经共享代理 → 壳 → `AppShell`
  透传，每一层对不认 `origin` 的旧签名都按 TypeError 退回不带。聚合态气泡（开始 / 完成 / 需要看一眼）本身不带
  会话，按「该通道最近一条记录的 sessionId」归属；审批 / 问题 / 失败的记录自带。
- **标题定格在记录时**（`AppShell._record_message`）：先查「最近的对话」，再查在用的会话登记表；会话关了记录
  仍完整。认不出的 Claude Code 会话用通道名，DSH 等通道与 Slack 总结记成肥鱼自己的消息（标题「大肥鱼」，点了不动）。
- 旧 `PetWindow` 拓扑没有记录服务，岛上不画铃铛。

### 今日用量与近 7 天仪表盘

- **口径**：用量 = 输入 + 输出 + 缓存写入；缓存读取单列、不计入。按 `(message.id, requestId)` 去重、字段取最大；
  按本机时区自然日。
- **账号 = 一组根 + 一只增量表。** 账号键只有 `windows`（本机 `~/.claude/projects`）和 `wsl`（每个在运行的发行版、
  每个 `home/<用户>/.claude/projects` 合成一只表）。没装 WSL → `wsl_projects_roots` 返回 `None`，只有一个账号，
  文案与单账号时一字不差；装了但读不到 → `[]`，显示 `WSL --`。
- **不碰没在运行的发行版**：`\\wsl.localhost\<发行版>` 的文件服务跑在发行版里，访问共享会把它拉起来；每分钟
  读一次等于让它永远关不掉。所以先问 `wsl.exe --list --running --quiet`（约 0.1 s，无窗口子进程），只读在跑的。
  同理不要用在发行版里执行命令的办法（`wslpath` 之类）找根。
- **读不到不丢数**：`reachable` 为假且当天一条都没读到才报 `--`；读到过就继续报上一次的数。
- **枚举用 `os.scandir`**（`transcript_files`）：目录项在 Windows 上自带 mtime，不另发 `stat`；子代理目录只看窗口内
  动过的会话下面的。旧的 `glob` + 逐个 `stat` 在 UNC 上每次都是一次 9P 往返：约 1000 个项目目录一遍 2.7 s，
  现在 1.1 s。稳态每分钟约 1.3 s 的后台 I/O，全在 WSL 侧；没有 WSL 的机器约 2 ms。
- **UI 线程不读文件**：统计在 `ClaudeUsageMonitor` / `UsageDashboard` 的 daemon 线程里，在途只有一次，换代作废。
- **文案在纯模块里拼**（`headline` / `detail` / `headline_segments`）。岛不解析文案字符串：监视器另发一份
  `[(账号键, 短名, 数字)]`，Metro 磁贴按账号键画记号（`_ACCOUNT_GLYPHS`：四格窗 / Ubuntu 一环三点），
  不认识的键画短名；非 Metro 样式照画整段文字。
- 仪表盘分账号时每天并排几根柱（第一根实心、其余空心），读不到写 `--` 不写 0。

### 名字与图标

- 名字走 `Config.character_display_name` 的顺序：用户别名 → manifest `name` → 角色 id。岛上的
  `_character_name` 别名每次现取（菜单改名下一次重绘就生效），manifest 名按角色 id 缓存——读盘 + 解析约
  0.46 ms，而这个方法每帧都被内容缓存键调用。
- 设置页「名字」写的就是 `character_aliases[当前角色]`，与右键菜单改名是同一个值。`save_island_name` 只在值与
  打开时不同才写、只写当前角色：保存前会重读配置，无条件写回会把设置开着时从菜单改的名字冲掉。
- 图标 `dynamic_island.icon` = `auto`（鱼本体头像）/ `img:<路径>` / 文字（旧的 emoji 设置，不动就原样保留；
  设置页不画 emoji 本身，首次画会加载彩色字体栈约 +33 MB）。
- 选图即**复制一份**到配置目录 `island-icons/`：最长边缩到 128、存 PNG、文件名 `icon-<内容 SHA-1 前 12 位>.png`。
  复制是因为原图会被清理或变成云端占位；缩到 128 是因为岛把位图原样常驻内存（4000×3000 约 46 MB，128 见方
  64 KB）；哈希命名让换图必然换配置值，岛按配置值清缓存的逻辑自然生效。
- 选好 / 恢复默认**立刻落盘**（`write_icon_now`）：只改磁盘上配置里这一项，不整份写回——设置开着时肥鱼也在写
  配置（拖岛记位置），整份写回会把它冲掉。写上之后才 `prune_icons` 清旧副本。并发模型见 [配置与数据](config-and-data.md)。

### 肥鱼隐藏时

- 隐藏肥鱼后单击岛照常展开卡片，恢复入口是卡片上的「显示肥鱼」；隐藏时点卡片的「聊天」直接开完整聊天窗。
- 配置键 `dynamic_island.hidden_chat` 和 `pet/island_chat.py` **不能删**：隐藏期间联动提醒 / AI 回复到达时用它在岛上弹预览；
  更要紧的是「隐藏期间联动监视器不暂停」的条件（`_island_feedback_available`）挂在这个开关上，删了岛上的会话状态在隐藏期间会停更。
- overlay 拓扑下 `AppShell` 里只遍历 `instances[].win` 的代码是空转（`win` 恒为 `None`）。涉及岛状态的动作要交给
  `OverlayShell`（例如 `set_pet_visible`，它在显示之后自己同步岛状态），否则会把岛状态写成「已完成」而实际什么都没做。

### 连接图标与「模型连接」面板

- 连接图标只表达聊天**在用**、且**已保存到盘上**的那一项：`ApiKeyMonitor` 启动 3 s 后查一次，通过后 30 分钟、
  失败后 5 分钟复查；悬停说明以「服务名 · 」开头（`service_name`）。
- **设置里的「测试连接」测的是表单，岛查的是已保存的。** 表单没保存时两边说的不是同一个服务，这不是刷新
  链路坏了（保存 → 主进程去抖重读 → 重新体检 → 岛变色，有端到端测试守着）。测试通过且
  `_form_differs_from_saved()` 为真时，结果下多一行「还没保存」。只比连接字段（地址、模型、Key、证书校验），
  基准是 `config.chat_settings()`（页面里的 `self.settings` 混着草稿，不能用），在点下去那一刻算好。
- 点连接图标（`link_rect()`）发 `connections_requested`，不展开卡片。面板里在用项直接读 `ApiKeyMonitor` 的结论，
  不重复发请求；其余各项打开时各查一次（同一个体检函数），按指纹缓存 30 分钟（`RECHECK_AFTER_S`）。指纹 =
  地址、路径、模型、接口格式、证书校验 + Key 的 SHA-256 前 12 位，变了立刻重查。每次发起带递增代号，
  代号对不上的晚到结果丢弃。面板没有定时器，关着零开销。

### Metro 磁贴

- **倾斜按尺寸限幅**（`metro_tilt_params`）：角度按「长边 / 28」反比缩小、透视视点等比拉远；长边 ≤ 28 的方块
  用原值。原参数（24°）套在 150 px 宽的磁贴上边缘要挪 26.6 px，限幅后 1.1 px。新加宽磁贴不要绕过它。
- **阴影只用现成的余量**：条底下三层（`_METRO_BAR_SHADOW`）最远伸到 `_CAPSULE_INSET`（6 px）为止，磁贴四周两层
  （`_METRO_BLOCK_SHADOW`）≤ 2 px = 磁贴与条边的间距；不扩窗口、不改布局。磁贴阴影画在 `_paint_metro_block`
  里、与磁贴同一个变换（悬停那块跟着倾斜）；卡片展开时不画条的阴影，否则在卡片底板上是一道黑边。
- 方角、实色、无描边、白字。「模型连接」磁贴底色即状态（绿 `#008a00` / 红 `#c50f1f` / 钢灰 `#5d6b7a`，
  对白字对比度 ≥ 4.5）。仪表盘与面板是透明底窗口：磁贴靠多层阴影浮起来，页头页脚用反色光晕文字（`_HaloLabel`）。

## 设计取舍

- **任务栏那一侧不停靠、盖不盖任务栏，都不做成设置项。**「细条贴在任务栏上沿」没人要；盖不盖由用户拖到哪决定。
  也不只对底边特判——任务栏可以在任何一边。代价：岛盖住的那段任务栏点不到。
- **看门狗用 2 s 轮询，不用 `WinEventHook`。** 后者要常驻消息钩子且 `EVENT_OBJECT_REORDER` 极密；只靠 30 s 心跳
  又太慢。实测外来置顶窗盖上去 1.76 s 后岛回到最上，一轮约 118 µs。
- **置顶是每一行自己的状态**，没有全局开关、快捷键或拖动排序；置顶的会话即使 transcript 被删也留着，靠「从列表
  移除」清掉。
- **岛上不再铺 Windows 通知中心的内容**，那条链路只喂自家弹窗，见 [通知](notifications.md)。
- **不单独给岛起名**：同一条鱼在岛上和菜单里叫两个名字更糊涂。名字跟随「保存」，图标选好立刻生效——逐字
  输入时每个字都写盘没有意义，而选图后还要点保存会让人以为没反应。也没有给内置角色包补默认 `name`。
- **图标不提供裁剪**，GIF 只取第一帧；emoji 选项已去掉。
- **只定时体检在用的服务**，其余按需；设置里测试通过**不**把岛变绿——测的是没保存的表单，变绿就是在撒谎。
  面板磁贴不可点进编辑，只给「去设置修改」。
- **WSL 用量稳态 1.3 s / 分钟先接受**。按项目目录 mtime 缓存可压到 100–200 ms，但 `--resume` 追加旧文件不改
  目录 mtime，没做。
- **来源只分到程序**：本机终端不区分 PowerShell / Windows Terminal / cmd，WSL 不分发行版。

## 外部格式依赖

- **Claude Code 对话记录**：`~/.claude/projects/<项目>/<会话>.jsonl` 与 `<项目>/<会话>/subagents/*.jsonl`；记录里的
  `timestamp`、`requestId`、`message.id`、`message.usage` 的 `input_tokens` / `output_tokens` /
  `cache_creation_input_tokens` / `cache_read_input_tokens`。同一条回复会写多行，后写的数更大。
- **WSL**：`wsl.exe --list --running --quiet` 的输出（要 `WSL_UTF8=1`，否则有 UTF-16 残渣）；共享路径
  `\\wsl.localhost\<发行版>\home\<用户>\.claude\projects`；发行版名来自注册表（`vscode_workspaces.wsl_distros`）。
- **Windows 外壳窗口类名**：`_SHELL_SURFACE_CLASSES`（`Shell_TrayWnd`、`Windows.UI.Core.CoreWindow`、
  `XamlExplorerHostIslandWindow` 等）；系统升级后开始菜单 / 任务栏弹出层若被岛盖住，先核对这张表。
- **来源图标取自本机程序**：VS Code 的 `Code.exe`、`Program Files` 下的 `pwsh.exe`（没有就 `powershell.exe`）、
  `System32\wsl.exe`、商店版 Claude 桌面版（注册表 `AppModel\Repository\Packages` 里 `Claude_` 开头的包）。
- **体检接口**：Claude 通道用 token 计数接口（不花输出额度），OpenAI 兼容通道发 `max_tokens=1` 的请求。

## 排障

| 症状 | 原因 / 先查什么 |
|---|---|
| 「岛不见了」 | 多半还在：看日志里最后一条「灵动岛拖拽落点」，再枚举窗口看岛的矩形。历史上是展开后收起留在被顶到的位置（`_rest_anchor` 的来历） |
| 岛拖到任务栏附近被收成细条 | 松手日志里的 `可停靠 …` 列出了哪几条边参与判定；自动隐藏的任务栏不预留工作区，底边照常可停靠（已知，未改） |
| 展开时胶囊原地上下轻跳、或整块卡片闪一帧 | 有人在动画里逐帧改了窗口几何，或动画中 `_update_size` 直落了终点尺寸 |
| 岛上列表的右键菜单被岛挡住 | `reassert_topmost` 的 Popup 门被绕过了 |
| 右键菜单透明底、字看不清 | `_card_box` 的无选择器样式表 `background: transparent` 会继承给 `QMenu(self)`；菜单要过 `style_island_menu` |
| 岛被别的窗口压着不回来 | 日志搜「灵动岛被 … 盖住，重新置顶」；没有这行就查 `topmost_hold_off`（前台是否外壳 / 真全屏）和压着的窗是否 cloaked |
| 岛和通知卡片互相压、闪 | 「自家窗口不算盖住」那一位被改掉了 |
| 用量显示 `WSL --` | 发行版没在运行（有意不拉起）；或共享刚起来，几秒内 `os.scandir` 报 `WinError 3`，下一分钟自愈 |
| 找不到 WSL 的对话记录 | 只找 `home/*`：`root` 的家目录在共享上拒绝访问；`os.listdir('\\\\wsl.localhost\\')` 报错，不能靠列共享根发现发行版 |
| 量 UNC 性能数字对不上 | PowerShell `Get-ChildItem` 逐项取属性，同一棵树 50 s 对 Python 的 1.1 s；Git Bash 沙箱里起的 Python 访问 `\\wsl.localhost` 直接 `WinError 3`，要从 PowerShell 起 |
| 测试连接成功，岛还是红的 | 表单没保存。悬停连接图标看「服务名 · 」是不是刚测的那个，再看盘上 `active_provider` |
| 选了图标岛没换 / 又变回默认 | 正常是选完约 0.6 s 换上（配置监视器去抖后重画）。看盘上 `dynamic_island.icon` 是不是 `img:`、`island-icons/` 里副本在不在；值是 `auto` 且目录空 = 之后按过「恢复默认」 |
| 岛上名字是角色 id | 没起别名，且该角色包的 `manifest.json` 没有 `name` |
| 来源图标是通用程序图标 | 候选路径里混进了 `WindowsApps` 下的执行别名（`wt.exe` 那种），外壳给不出本尊图标 |
| 消息记录里没有某条气泡 | 它没走 `show_bubble` / `show_alert`，或带了 `record=False`，或 60 s 内同会话同文案被去重 |
