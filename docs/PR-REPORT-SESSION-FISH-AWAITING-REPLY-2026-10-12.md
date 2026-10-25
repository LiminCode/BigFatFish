# PR 报告：会话小鱼的「等你回复」——做完了、你还没去看的对话单独标出来

> **基线**：`8083b2f`（fix(session-fish): 会话小鱼的名字跟着用户给会话改的名字走）
> **分支**：`feature/claude-session-fish`　**日期**：`2026-10-12`
> **范围**：14 个文件（实现 5、测试 5、文档 4 含本报告与索引）
> **关联**：[`PR-REPORT-CLAUDE-CODE-SESSION-FISH-2026-10-11.md`](PR-REPORT-CLAUDE-CODE-SESSION-FISH-2026-10-11.md)、
> [`AGENT_LINK_PROTOCOL.md`](AGENT_LINK_PROTOCOL.md) §3.1

## 一、核心特性

用户反馈：每个对话的小鱼在回合一结束就进入「休息中」、标签变成深灰。同时开着好几个
对话时，「做完了等我去看」和「早就看过、闲着」长得一模一样，分不出哪些工作需要查看。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 新状态「等你回复」 | 回合结束后小鱼不直接休息，停在「等你回复」；标签天蓝底、深蓝字 |
| 2 | 看过才休息 | 点「跳到对话」（详情卡按钮、右键菜单「跳到这个对话」、灵动岛「最近的对话」里点一行）后落回「休息中」；直接在那个对话里接着提问也会清掉 |
| 3 | 动作不同 | 等你回复时轮播 `工作状态-雀跃庆祝` / `工作状态-原地踱步张望`，不再躺下睡觉；看过之后才是 `原地小憩沉眠` |
| 4 | 灵动岛分得出 | 胶囊计数多一项蓝字「N 待回复」；汇总卡片的「N 个等你回复」排在「在干活」前面 |

四种状态的标签（真实代码、真实字体渲染，见 §五）：

| 状态 | 底色 | 含义 |
|---|---|---|
| 工作中 | 淡绿 | 在干活 |
| 等你批准 | 深灰（未改） | 停在权限确认上 |
| **等你回复** | **天蓝** | **回合结束，你还没去看** |
| 休息中 | 深灰（未改） | 看过了，闲着 |

**红线 / 不变量**

- 收敛器（`ClaudeSessionTracker`）不变：它照旧只报 `working / waiting / resting / gone`。
  「看过没有」是呈现层的事，Agent 级状态管线（主肥鱼）完全不受影响。
- 桌宠启动时就已经停着的会话仍是「休息中」，不会一启动就一片蓝
  （`test_controller_keeps_a_session_registry_independent_of_the_fish` 里第一次见到就是
  `resting` 的会话保持 `resting`）。
- 「不为停着的会话凭空生一只鱼」不变：等你回复的会话如果此刻没有鱼（到上限、被退掉），
  同样不生（`test_dismissed_fish_returns_on_the_next_prompt_not_before`）。
- 阶段没变时不重启动画（`test_repeated_updates_do_not_restart_the_animation`）。

## 二、修改文件说明

增删取自 `git diff --cached --numstat`（基线 `8083b2f`）。

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/overlay_session_pets.py` | +46 / −6 | 核心。`_unseen` 集合记「回合结束了、用户还没去看」的会话；`_presented_phase()` 把收敛器报的阶段换成显示的阶段——从 `working` / `waiting` 转入 `resting` 的会话记为没看过并显示成 `review`，其余非 `resting` 的阶段清掉记号；`acknowledge(key)` 供「看过了」调用，清记号后把登记表里的内容回放一遍，走既有的标签 / 动画 / 通知路径。阶段起始时刻（`since`）在 `review → resting` 时不重置：详情卡的「已 N 分钟」仍从回合结束算起。新增 `REVIEW_CLIPS`。会话离场时清记号。两条 INFO 日志（进入等回复 / 已看过），实机排查用 |
| `pet/session_pet_ui.py` | +11 / −0 | `jump_key()`（三个跳转入口的共同出口）开头调 `acknowledge`；真的改了就用 `_refresh_card()` 把开着的详情卡状态行同步过来 |
| `pet/claude_hooks.py` | +9 / −5 | 文案表加 `review`：`PHASE_TEXT`「等你回复」、汇总计数「N 个等你回复」、胶囊短标签「待回复」；汇总排序改为 等批准 → 等回复 → 在干活 → 休息 |
| `pet/pet_sprite.py` | +3 / −1 | `_CAPTION_TONES` 加 `review`：底 `(150, 200, 255, 240)`、字 `(10, 44, 102)` |
| `pet/dynamic_island.py` | +2 / −2 | `_SESSION_COUNT_COLORS` 加 `review: #3b8fe8` |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_overlay_session_pets.py` | +49 / −3 | 3 条新增：回合结束 → 等你回复（标签 / 色调 / 动画 / 登记表）、回合结束后才到的标题和改名不把它冲回休息、`acknowledge` 后落回休息且不重置计时、看过之后不会自己变回去；下一次提问清掉、下一次结束再亮起；不认识的会话无害。1 条既有用例的期望随行为改变（回合结束后是「等你回复」而不是「休息中」） |
| `tests/test_session_pet_details.py` | +35 / −0 | 详情卡「跳到对话」按钮与右键菜单的跳转都把会话标成看过，开着的卡片状态行同步；状态行文案 |
| `tests/test_claude_hooks.py` | +13 / −0 | 计数与汇总里 `review` 单列、排序 |
| `tests/test_sprite_caption.py` | +8 / −0 | `review` 色调的胶囊是蓝的 |
| `tests/test_island_status_indicator.py` | +19 / −0 | 胶囊上「待回复」比「休息中」多出蓝色像素 |

### 文档

| 文件 | 增删 | 内容 |
|---|---|---|
| `README.md` | +4 / −3 | 会话小鱼的状态从三种写成四种，新增「做完了等你来看」一条；灵动岛计数示例 |
| `docs/AGENT_LINK_PROTOCOL.md` | +1 / −1 | §3.1 说明 `review` 是呈现层的派生阶段、谁设谁清 |
| 本报告、`docs/INDEX.md` | 新增 / +1 | 登记 |

### 未改动

- `ClaudeSessionTracker`（收敛器）与 hook 脚本：不需要新事件，也不新落任何数据。
- 详情卡的五套配色（`session_card_themes.py`）：状态行沿用方案里的正文色，没有给
  「等你回复」单独上色——每套方案的对比度都有测试把关，加一个强调色要逐套重验。
- 「等你批准」的标签仍是深灰。它比「等你回复」更急，按理也该有颜色（灵动岛里它是橙字），
  但不在这次反馈的范围里，留作后续。

## 三、实现要点

**为什么放在呈现层而不是收敛器。** 收敛器在监视器的 worker 线程里，吃的是 hook 事件，
它能知道的只有「回合结束了」。「用户看过没有」来自界面上的一次点击，发生在 GUI 线程。
放进收敛器就得跨线程回写它的状态；放在 `SessionPetController`（GUI 线程上，本来就是
「收敛器的阶段 → 屏幕上的样子」那一层）只是一个集合加一个纯函数。

**为什么是「记号集合 + 回放」。** 标题更新、用户改名（`retitle`）都会把登记表里的内容
再送进 `on_session_update`，其中的阶段可能是 `resting`（收敛器来的）也可能是 `review`
（自己登记表里的）。`_presented_phase` 先把回放进来的 `review` 还原成 `resting`，再按
「在不在 `_unseen` 里」决定显示什么，所以两种来源走同一条判定；`acknowledge` 也只需要
清记号再回放一遍，标签、动画、`sessions_changed` 通知全部复用既有路径。

**什么算「看过」。** 只有两件事：点了「跳到对话」，或者那个对话又开始干活了（用户直接
回复了）。点开详情卡不算——详情卡上看不到 Claude 的回答，只看得到最近的问题。跳转在
点击那一刻就算数，不等跳转结果：跳转失败时卡片 / 气泡会给出原因，用户已经知道这个
对话的情况。

**为什么是蓝色。** 绿色是工作中；灵动岛里橙色已经给了「等你批准」（最急）。蓝色是
「有未读」的惯用色，与绿、橙、深灰都分得开，日后给「等你批准」的标签上橙色也不冲突。

**没有采用的做法**

- 回合结束时弹气泡 / 响提示音：主肥鱼的 Agent 级管线已经在做（「需要你看一眼」），
  每只小鱼再各弹一次是重复打扰。
- 把「看过没有」落盘：重启后小鱼本来就要等会话的下一次事件才重新出场，落盘的记号
  没有对应的鱼可以标。
- 用「那个窗口是否在前台」自动判定看过：要常驻轮询前台窗口，而且 VS Code 一个窗口
  里可以有多个对话，判不准。

## 四、性能分析

**方法（可复现）**：一次性脚本（会话内，未入库）用替身 shell 构造一个
`SessionPetController`，重复调用 `on_session_update` / `acknowledge`，
`time.perf_counter_ns` 计时，每项 30 轮 × 2,000 次取中位（`_presented_phase` 单测是
30 轮 × 20,000 次）。基线数字是把 `pet/` 的改动暂存起来后用同一脚本测的。
环境：Windows 11 10.0.26300，Python 3.13.15，全量测试结束后空闲时测。

| 指标 | 基线 `8083b2f` | 改动后 | 归属 |
|---|---|---|---|
| 一个回合（`working` → `resting` 两条更新） | 3,850 ns | 4,416 ns | 既有路径，每个会话每回合 1 次 |
| 内容不变的重复更新 | 1,397 ns | 1,617 ns | 既有路径 |
| `_presented_phase` 单次 | — | 176 ns | 新增，每条逐会话更新 1 次 |
| 一个回合 + `acknowledge` | — | 7,065 ns | 新增，用户每点一次「跳到对话」1 次 |

**结论**

1. **稳态开销**：没有新的定时器、轮询或逐帧工作。逐会话更新每条多约 0.2 µs
   （一次集合查找 + 几次字符串比较）；这条路径的频率是每个会话每回合几条。一个回合
   合计多 0.57 µs。
2. **新增路径**：`acknowledge` 约 2.6 µs（7,065 − 4,416），只在用户点「跳到对话」时
   发生。标签换色调时胶囊贴图重画一次（既有机制：文本或色调变了才重画，之后贴图）；
   每个回合比原来多一次换色（`review → resting`），没有单独计时。
3. **新的系统调用 / 网络 / 磁盘 / 线程**：都没有。两条 INFO 日志各在状态切换时写一行
   （每回合至多 1 行、每次跳转至多 1 行）。
4. **内存**：`_unseen` 每个等回复的会话一个二元组；会话离场、看过、再次提问时移除，
   上限是在用的会话数（收敛器的会话表上限 64）。

## 五、实机运行记录

**问题的现场**：用户提供的桌面截图——一只小鱼头顶是「（会话标题）· 休息中」，详情卡
状态行「休息中 · 已 11 分钟」，而这个对话的结果用户还没看过。

**重启桌宠加载新代码**（先确认没有设置窗口进程在跑）

```text
stopping 5212
2026-10-12 14:23:51 acquired pid=56872 lock=%APPDATA%\big-fat-fish\overlay-instance.lock
```

**整条链路的探针**：用数据目录里那份真实的 hook 脚本（`claude_event_hook.sh`，经 Git
Bash）往真实的 `agent-events/claude.jsonl` 喂一个探针会话，读运行中桌宠的日志
（`pet-56872.log`）。走的是 hook 脚本 → 事件文件 → 监视器线程 → 收敛器 → 排队信号 →
`SessionPetController` → 真实 sprite 的完整路径。

```text
session probe-review-1791840259 | script claude_event_hook.sh exists True
--- after UserPromptSubmit: 1 log line(s)
    2026-10-12 14:24:20,413 INFO 会话小鱼出场 agent=claude session=probe-re（在场 3 只）
--- after Stop: 2 log line(s)
    2026-10-12 14:24:21,900 INFO 会话回合结束，等用户来看 agent=claude session=probe-re
--- after UserPromptSubmit: 2 log line(s)
--- after Stop: 3 log line(s)
    2026-10-12 14:24:24,901 INFO 会话回合结束，等用户来看 agent=claude session=probe-re
--- after SessionEnd: 4 log line(s)
    2026-10-12 14:24:26,422 INFO 会话小鱼离场 agent=claude session=probe-re
```

- 回合结束 → 进入等回复：确认。
- 再次提问清掉记号、下一次结束重新亮起：确认（第二次 `Stop` 又记了一行；如果记号没被
  第二次 `UserPromptSubmit` 清掉，`previous` 是 `working` 仍会记，所以这一条单看日志只能
  证明「再次结束会再亮」，「提问时清掉」由用例
  `test_the_next_prompt_clears_the_reminder_and_the_next_finish_raises_it_again` 证明）。
- 会话关闭 → 小鱼离场：确认，探针没有留下残留的鱼。
- 重启后日志里没有 `ERROR` / `Traceback`。

**标签的样子**：用真实的 `PetSprite.caption_pixmap()`、真实平台字体（不是 offscreen）把
四种状态各渲染一张，分别放在浅色和深色底上看过：「等你回复」是天蓝底深蓝字，与淡绿的
「工作中」、深灰的「等你批准」「休息中」一眼分得开，字清楚。

**没有验证的部分**

- **没有在真实桌面上看到小鱼变蓝，也没有真的点过「跳到对话」。** 本会话没有驱动桌面
  鼠标的手段，也没有截取用户的屏幕。「点了之后落回休息中」只有用例覆盖
  （`test_jumping_to_a_finished_session_marks_it_as_seen` 真点了详情卡上的按钮，但后端
  的切窗是注入的）。需要用户在下一个对话结束后确认：标签变蓝、小鱼在庆祝 / 张望；
  点「跳到对话」后变回深灰的「休息中」并睡下。
- **两段新动画在小鱼尺寸（主肥鱼的一半）下的观感没有人眼确认。** 只核对了这两个文件
  在角色包里存在（`videos/random/工作状态-雀跃庆祝.webm`、`工作状态-原地踱步张望.webm`），
  名字与素材库的取名规则（文件名去扩展名）一致。
- 灵动岛上蓝字「待回复」只有离屏渲染的像素断言，没有在真实胶囊上看过。
- WSL 通道没有单独探测：两个通道进的是同一个 `on_session_update`，只是 `agent_key` 不同。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests`、`git diff --check` | 通过 |
| 红 → 绿 | 下面 5 个文件 | 实现前 `4 failed, 115 passed, 23 errors`（errors 是夹具给还不存在的 `REVIEW_CLIPS` 打补丁）；实现后 142 passed |
| 断言有效性 | 把 `pet/dynamic_island.py` 的改动单独撤掉重跑 `test_island_status_indicator.py` | `1 failed, 7 passed`（失败的正是新用例），恢复后 8 passed |
| 聚焦 + 相关 | `test_overlay_session_pets` `test_session_pet_details` `test_claude_hooks` `test_sprite_caption` `test_island_status_indicator` `test_island_shell_wiring` `test_island_card_text` `test_session_custom_title` `test_session_card_themes` `test_island_session_history` `test_claude_link` | 268 passed（在最终代码上） |
| 受影响时序族满载 3 遍 | — | 不适用：新用例里唯一等后台线程的地方沿用既有的 `_pump` 事件循环轮询（20 秒预算，不 sleep），没有新增时序假设 |
| 全量 | `python -m pytest -q -p no:cacheprovider`（`QT_QPA_PLATFORM=offscreen`，`APPDATA` 指向临时目录，从 Git Bash 启动） | `5 failed, 5024 passed, 11 skipped in 479.03s`。5 个失败是这台机器上一直存在的环境性失败（路径超 260、三条子进程输出编码、多显示器负原点），与本改动无关。这次运行之后只加了两条日志语句和文档，之后重跑了上面的「聚焦 + 相关」 |

## 七、已知限制与后续

- 「看过」只认「跳到对话」和「接着提问」。用户自己切到那个窗口看了、但没有回复，小鱼
  会一直是「等你回复」，直到点一次「跳到对话」。
- 用户按 Esc 打断的回合不发 `Stop`，要等 Claude Code 60 秒后的 `idle_prompt` 才算结束
  （既有行为），所以打断后约一分钟小鱼才变成「等你回复」。
- 记号只在内存里：桌宠重启后清空（重启后小鱼本来也要等会话的下一次事件才出场）。
- 换了没有这两段动画的角色时，等你回复期间小鱼退回随机行为（既有的缺素材兜底），
  标签和颜色照常。
- 「等你批准」的标签还是深灰，后续可以给它橙色。

## 八、风险与回滚

- **影响面**：会话小鱼的标签 / 动画、灵动岛的会话计数与汇总文案。主肥鱼的状态管线、
  审批提醒、hook 脚本、事件文件格式都不变。
- **配置 / 落盘**：没有新增配置键，没有新的落盘数据。
- **回滚**：`git revert` 后重启桌宠即可，无残留状态。
