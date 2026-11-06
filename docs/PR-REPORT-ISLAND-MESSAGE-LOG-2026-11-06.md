# PR 报告：灵动岛「通知」换成「消息记录」——肥鱼冒过的通知气泡都留着（2026-11-06）

> **基线**：`64e1e54e`（main，Merge PR #23「岛可以盖在任务栏正上方」）
> **分支**：`feature/island-message-log`　**日期**：2026-11-06
> **范围**：19 个文件（实现 11、测试 8；另加本报告 + `INDEX.md` 登记）
> **关联**：`PR-REPORT-NOTIFICATION-CENTER-2026-10-14.md`（被替换掉的岛上 Slack 通知框）；
> `PR-REPORT-NOTIFICATION-TOASTS-2026-10-28.md`（自家弹窗——保留，只是不再往岛上铺）；
> `PR-REPORT-HISTORY-PIN-2026-10-20.md`（「最近的对话」折叠框，消息记录照它的样子做）

## 一、核心特性

用户 2026-11-05：岛展开的卡片里「通知」铺的是 Windows 通知中心里的 Slack 通知，不要了；换成**最近会话的
通知**——像每只会话小鱼的卡片那样写明是哪个对话，然后是通知内容；大肥鱼自己的通知（周期性的 Slack 总结等）
也要留着。「总之，大肥鱼头上冒泡出现的通知，都要留存在这个通知里面」，也可以叫「消息记录」。

现状可测量：气泡几秒就收（联动气泡 3–6 s，Slack 总结的提醒要点掉），错过了就没了；实机日志里当天有
8 次「通知跳转：launched（slack / protocol）」——那条 Slack 通知链路保留在自家弹窗上，岛上的框换掉。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 消息记录 | 新模块 `pet/message_log.py`：壳的 `show_bubble` / `show_alert` 与肥鱼隐藏时改道到岛的反馈气泡，每条先记一笔再管显不显示。落盘 `message-log.json`（配置目录），留最近 200 条，看没看过跨重启记得 |
| 2 | 写明是哪个对话 | 联动管理器给每条气泡带上来源（通道 + 会话 id）；记录时定格成会话小鱼卡片上那个标题、从哪开的（VS Code / 终端 / WSL / Claude 桌面版图标）、工作目录——会话关了记录还在 |
| 3 | 岛上的「消息记录」折叠框 | 原来的「通知」框换成 `island_message_panel`：同一套 Metro 卡片，一行是对话标题 + 多久以前 + 两行正文；大肥鱼自己的消息标「大肥鱼」画一条小鱼。铃铛 = 没看过的条数。点一行切到那个对话（还开着）/ 恢复它（关了）；右键 移除 / 清空 |
| 4 | Windows 通知中心只喂弹窗 | 服务不再推岛；读取开关 + 弹窗开关都开着才轮询，关了停表（原来只要读取开着就 3 s 一轮，读了没人看） |

**红线 / 不变量**：气泡本身怎么弹一条不变（记录在门禁之前，记了 ≠ 弹了）；自言自语、识屏答复、会话小鱼动作
回执（「已复制」）不走 `show_bubble` / `show_alert`，不进记录；**过程汇报气泡**（「正在读文件…」，每次工具调用
一条）显式不记（`record=False`），否则记录会被它淹掉；旧 PetWindow 拓扑没有记录服务，岛上就不画铃铛（和原来
「没接通知服务」一样）；自家弹窗、设置页「通知」域、`notifications` 配置键都不动。

## 二、修改文件说明

`git diff --cached --numstat`（相对 `64e1e54e`）：

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/message_log.py`（新） | +253 | `Message`（uid / at / text / subtitle / kind / agent / session_id / title / host / where / path）与 `MessageLog`：`record`（空文案不记；60 s 内同会话同文案只记一次——审批气泡重新挂上、隐藏期改道再来一遍都是同一条）、`mark_all_seen`（`seen_uid` 水位，跨重启）、`remove` / `clear` / `retitle`、`listeners`、原子落盘（tmp + replace），坏文件 / 坏条目 / 重复编号都丢掉 |
| `pet/island_message_panel.py`（由 `island_notification_panel.py` 改成） | +75 / −72 | `MessagePanel` / `_MessageRow`：行数据是 `title / text / subtitle / ago / unread / host / where / path / session`；图标按 `host` 取 `host_icons`（与「最近的对话」同 16px，共用预热缓存），没有会话的画 `pet` 记号；标题空就写「大肥鱼」；菜单按行是不是会话二选一（会话行多一项「切到这个对话」）。不再有应用 logo PNG / `in_center` 那套 |
| `pet/dynamic_island.py` | +61 / −63 | 公开面改名：`set_messages`（去掉 `logos`）/ `set_message_count` / `message_tooltip` / `message_button_rect` / `show_message_status`，信号 `messages_requested` / `message_activated` / `message_action` / `message_toggled`；铃铛文案键 `island.messages.*`；注释按「消息记录」改。铃铛的画法、排版、点击展开卡片并打开框的行为不变 |
| `pet/overlay_shell.py` | +25 / −5 | `message_sink`（AppShell 注入）+ `_note_message`：`show_bubble` / `show_alert` 进来**先**记（在可见 / 抑制 / 飞行门禁之前；`origin["log"] is False` 的不记），记录出错只写日志不影响冒泡；两个方法多一个 `origin` 参数并传给 `window_alerts.show_alert` |
| `pet/agent_link.py` | +47 / −16 | `_last_session_id[agent_key]`（`_remember_dialogue_record` 里每条带 sessionId 的记录更新）；`_bubble_origin(agent_key, session_id="")` → `{"agent", "session_id", "name"}`；`_win_show_bubble`（窄签名的窗不认 `origin` 就不带）；`_show_link_bubble` 多 `agent_key` / `record` 两个参数，8 个调用点传 `agent_key`，过程汇报传 `record=False`；交互提醒（审批 / 问题 / cordis）、硬失败提醒经 `_show_alert_compat` 带 `origin`（TypeError 时连同 priority / alert_type / metadata 一起剥掉） |
| `pet/app.py` | +136 / −78 | 删掉 6 个把通知中心推上岛的方法（`_push_island_notifications` 等）；`_on_notification_activation_done` 只记日志。新增：`_start_message_log`（overlay 壳建好后建 `MessageLog`、接 `message_sink`）、`_record_message`（解析来源：先「最近的对话」、再在用的会话登记表 `describe`，都不认识的 Claude Code 会话用通道名；DSH 等通道记成大肥鱼的消息）、`_push_island_messages`（最多 50 行）、点一行 / 右键 / 折叠 / 打开的 4 个处理；`_island_feedback_bubble` 多 `origin` 并先记录；`_sync_notification_center` 改成「读取 + 弹窗都开着才轮询」且不再连岛；语言切换时连消息一起重推 |
| `pet/window_alerts.py` | +13 / −6 | `show_alert` / `redirect_hidden_bubble` 多 `origin`，隐藏期改道时原样交给注入方（旧注入方不认就不带） |
| `pet/multi_window_shared.py` | +14 / −6 | 代理的 `show_bubble` 透传 `**kwargs`、`show_alert` 透传 `origin`，窄签名的窗 TypeError 退回不带 |
| `pet/window.py` | +1 / −1 | `PetWindow.show_bubble` 吃掉 `**_ignored`：legacy 拓扑下带 `origin` 的调用不再 TypeError（只防崩，行为不变） |
| `pet/locale/zh.json` / `en.json` | +10 / −14、+11 / −15 | 删 `island.notifications.*`、`notices.header.*`、`notices.menu.*`、`notices.status.*`（都只有岛上的通知框在用）；加 `island.messages.*`、`messages.header.*`、`messages.menu.*`、`messages.pet`、`messages.status.gone`；`settings.notifications.enabled_hint` 改成「给弹窗供数，岛上现在是消息记录」。`notices.toast.*` 弹窗还在用，保留 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_message_log.py`（新） | +108 | 新的在前、uid 稳定、会话字段；去重窗口；未读水位跨重启、ui_open 一起存、编号不回绕；keep / remove / clear / 听众次数；retitle 只补空字段；坏文件；无路径只在内存 |
| `tests/test_island_messages.py`（新，替代 `test_island_notifications.py`） | +306 / −224 | 铃铛提示中英文、点铃铛展开卡片并打开框、没有记录服务时框整个不出现；面板：标题 / 正文两行 / 未读竖条 / 来源图标 / 悬停全文、大肥鱼行的标题与菜单、点击与菜单报 key、英文、不透明菜单样式；AppShell 接线（`AppShell.__new__` 桩 + 真 `MessageLog` + 真 `SessionHistoryService`）：5 种来源各自的标题 / 图标 / 目录、铃铛计数、打开即看过、隐藏期改道只记一次、点一行切到在用的会话 / 关了的提示 / 大肥鱼的不动、移除 / 清空 / 折叠状态落盘 |
| `tests/test_overlay_message_sink.py`（新） | +62 | 真 `OverlayShell`：气泡与提醒在门禁之前就记（设置页抑制、隐藏期照记，但隐藏期仍不冒泡）；自言自语不记；来源不是字典当没有；记录抛错气泡照出；没注入什么都不发生 |
| `tests/test_agent_link_message_origin.py`（新） | +104 | 真 `AgentLinkManager`：联动气泡带通道 + 最近一条记录的会话、全局提示不带；失败提醒与交互提醒带会话；窄签名的旧桩照样收到气泡和提醒 |
| `tests/test_island_metro.py` / `test_island_personal.py` / `test_single_process_shared.py` | 3 / 4 / 2 行 | 岛 API 改名跟着改（`set_message_count` / `message_button_rect` / `set_messages`） |

### 未改动

- `pet/notification_center.py` / `notification_service.py` / `notification_toast.py` / `settings_notifications.py` 与它们的
  测试：Windows 通知中心 → 自家弹窗这条链路原样保留（用户当天点了 8 次弹窗跳 Slack）。
- `pet/island_history_panel.py`：「最近的对话」没动；消息面板从它 import `_font` / `style_island_menu` / `tile_colors` / `HOST_ICONS`。
- `pet/session_pet_ui.py`：会话小鱼卡片没动；消息行的标题 / 来源用的是「最近的对话」同一份 `HistoryEntry.label / host / where`。

## 三、实现要点

- **记在哪**：`OverlayShell.show_bubble` / `show_alert` 的第一行（可见、抑制、飞行、提醒队列让路都在后面）。错过
  的气泡正是记录最有用的部分，所以「记了」和「弹了」是两回事；隐藏期联动气泡走 `redirect_hidden_bubble` →
  `AppShell._island_feedback_bubble`，那里也记——`show_alert` 隐藏期先记一次再改道，靠 60 s 去重合成一条。
- **怎么知道是哪个会话**：联动管理器的聚合态气泡（开始 / 完成 / 需要看一眼）本身不带会话；按「该通道最近一条
  记录的 sessionId」归属——触发这条气泡的就是那条记录。审批 / 问题 / 失败的记录自带 sessionId，直接用。
  来源只是个 `origin` 字典，经代理 → 壳 → AppShell 一路透传，每一层对不认 `origin` 的旧签名都 TypeError 退回。
- **标题定格在记录时**：`_message_session_info` 先查「最近的对话」（有 `label / host / where / cwd`），再查在用的
  会话登记表（`describe` → 临时 `HistoryEntry` 算同一套），会话关了、名册过期了记录照样完整；`retitle` 留给
  以后补标题用（本次没接，记录时认不出的只会是刚开第一句话的会话，很快就有下一条）。
- **为什么不记过程汇报**：实机 2 分钟进了 4 条「正在跑命令 / 正在读文件」——每次工具调用一条，一轮对话几十条，
  200 条的记录会只剩它们。显式 `record=False`，「开始干活」「干完活」「需要批准」「失败」「Slack 总结」都记。
- **岛上最多 50 行**：记录文件留 200 条，岛上只铺最近 50 条（见性能）。
- **通知中心服务的开关**：原来岛是它的主消费者，现在只剩弹窗；`enabled && toast.enabled` 才轮询，别的不动。

## 四、性能分析

**方法**：`QT_QPA_PLATFORM=offscreen`，`.venv` Python 3.13.15，Windows 11 26300；`timeit` / `perf_counter`，
脚本就是本报告写作时跑的那几段（记录 200 条、面板 50 / 200 行）。

| 指标 | 实测 | 归属 |
|---|---|---|
| `MessageLog.record` + 落盘（200 条满额，整文件重写） | 1.05 ms / 次（n=300） | 新增：每条通知气泡一次 |
| 文件大小（200 条） | 37.9 KB | 新增 |
| 启动加载 200 条 | 0.65 ms | 新增：启动一次 |
| `unread_count` / 去重命中（不落盘） | 4.0 µs / 0.5 µs | 新增 |
| 面板 50 行（来源图标已预热）：首次建控件 / 时间文字刷新 / 新来一条 | 12.5 ms / 3.3 ms / 4.9 ms | 新增：首次 + 每条通知一次 |
| 面板 200 行首次建控件（未封顶前） | 226 ms | 为此封顶 50 行 |
| 来源图标预热（VS Code 那个要外壳解包） | 176 ms | 既有：「最近的对话」启动 2.5 s 后已经在做，消息面板改用同尺寸共用这份缓存 |

**结论**：① 稳态无变化——没有定时器，记录只在气泡到达时动；② 新增路径 = 每条通知气泡 1 ms 记录 + 落盘
+ 约 5 ms 岛面板刷新（GUI 线程），触发频率是通知气泡的频率（一轮 Claude 对话 2–4 条；过程汇报不记）；③ 新增
磁盘写：每条通知一次 38 KB 以内的原子写（tmp + replace），没有新线程 / 网络 / 系统调用；通知中心轮询在
「读取开、弹窗关」这种配置下**少了**每 3 s 一次的 WinRT 读；④ 内存：≤ 200 条 `Message`（约 40 KB）+ 岛上 50 行
卡片控件（原来通知框最多 50 行，同量级）。

## 五、实机运行记录

本机：Windows 11，主屏 3840×1600 @125%，岛放在任务栏正上方（PR #23 之后）。

**改前**：旧桌宠（pid 55040，main 64e1e54e）日志里当天 8 条「通知跳转：launched（slack / protocol）」——
Slack 通知这条链路在用，所以只换岛上的框、弹窗保留。

**改后**：从本工作区重启（pid 22772，00:21:00，`pet-overlay-gate.log` acquired，`pet-22772.log` 无 WARNING /
ERROR，只有一条既有的 INFO「台词语音预缓存跳过：本地 TTS 服务不可用」）。本会话（Claude Code，从 Claude 桌面版开的）
的 hook 事件随即冒泡并进记录——`%APPDATA%\big-fat-fish\message-log.json` 在 2 分钟内：

```
uid kind   title                                            host    text
  4 bubble 悬浮岛今日 token 用量分 Windows / WSL 两账号显示 desktop Claude Code 正在当前会话 中读取 正在读文件。
  3 bubble 悬浮岛今日 token 用量分 Windows / WSL 两账号显示 desktop Claude Code 在当前会话 中执行到第 步，任务仍在运行。
  2 bubble 悬浮岛今日 token 用量分 Windows / WSL 两账号显示 desktop 当前会话 中，Claude Code 已通过 PowerShell 开始执行。
  1 bubble 悬浮岛今日 token 用量分 Windows / WSL 两账号显示 desktop Claude Code 正在当前会话 中运行 正在跑命令。
```

标题 = 这个会话在会话小鱼卡片 / 「最近的对话」里的标题，`host=desktop`（Claude 桌面版开的），`path` 是本工作区——
来源解析在真实 hook 链路上对了。这 4 条正是「过程汇报」：看到实机 2 分钟就 4 条，才加了 `record=False`
（这一版运行的进程还没带这个改动；合并后从主检出重启的那个带）。

屏幕探针（另一个进程：找到岛的 HWND，截图，`SetCursorPos` + `mouse_event` 点胶囊左端展开，再截图）：

```
capsule 25890924 (2488, 1543, 600, 55)        → real_island_capsule.png：铃铛琥珀色带角标
after click rect (2488, 340, 600, 1260)        → real_island_card.png：「消息记录 (3) · 收起」+ 3 张卡片
                                                 （会话标题 / 多久以前 / 两行正文 / Claude 桌面版图标），
                                                 下面是「最近的对话 (30)」
```

截图留在会话草稿目录，不入库。

**顺手发现（既有，不在本 PR 修）**：岛在屏幕下半部分时展开卡片被夹回屏幕（y 1543 → 340），收起后胶囊留在
340 不回原位——`_target_rect` 的普通分支按「当前左上角 + 胶囊尺寸」算，展开时被 `_clamp_rect` 上推的位移
没有记下来。main 上同样（#23 之前按工作区夹也一样），重启按配置里的位置回来。

**没在真机做的**：点一行切会话（跳窗链路和「最近的对话」同一条 `session_actions.jump_key`，离屏测试覆盖）、
Slack 总结提醒进记录（`show_alert` 路径离屏覆盖；下次 Slack 关注有新条目时记录里会有一条标「大肥鱼」）。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests scripts` | All checks passed |
| 聚焦（新 4 个文件） | `pytest -q tests/test_message_log.py tests/test_island_messages.py tests/test_overlay_message_sink.py tests/test_agent_link_message_origin.py` | 23 passed |
| 聚焦 + 相关族 | 上面 4 个 + `test_i18n test_island_metro test_island_personal test_single_process_shared test_app_notification_toasts test_notification_service test_settings_notifications test_island_shell_wiring test_overlay_chat_proactive test_architecture test_agent_link test_dynamic_island_revamp test_island_history_panel test_pr_report_discipline` | 496 passed, 1 skipped（16.6 s） |
| 全量 | `python -m pytest -q -p no:cacheprovider`（PowerShell 起，`APPDATA` 指到临时目录） | **6 failed, 5974 passed, 14 skipped in 570.95s**。6 个与上一个 PR（#23）报告里的同一组：4 个环境基线（`test_image_directory_picker…` / `test_festival_id_guard_survives_optimize` / `test_real_second_process_refused_on_overlay_topology` / `test_capture_window_rect_coordinates_and_clamping`）+ `test_host_icons_are_warmed_at_the_cards_size` + `test_modern_context_menu_has_compact_semantic_groups`，main 上原样失败，与本分支无关 |

## 七、已知限制与后续

- 记录里会话标题是记录那一刻的；会话后来改名不回头改（`retitle` 已有、没接）。
- 大肥鱼自己的消息没有可去的地方，点了不动；Slack 总结想看全文要去「工作简报」窗。
- 岛在屏幕下半部分展开再收起不回原位（既有，见五）。

## 八、风险与回滚

- 影响面：岛卡片里的那一个框、铃铛的数据来源、气泡调用链上多一个可选参数；弹窗、设置页、通知中心读取不动。
- 配置 / 数据：无新配置键；新文件 `message-log.json`（配置目录）。
- 回滚：revert 本 PR 的 squash 提交；`message-log.json` 留着无害。
