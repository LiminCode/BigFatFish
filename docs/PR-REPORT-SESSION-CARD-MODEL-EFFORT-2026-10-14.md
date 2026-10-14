# PR 报告：会话小鱼的详情卡显示在用的模型与 effort

> **基线**：`72dfcd9`（feat(i18n): 界面语言第一片）
> **分支**：`feature/claude-session-fish`　**日期**：`2026-10-14`
> **范围**：5 个文件（实现 2、测试 1、文档 2 含本报告）

## 一、核心特性

用户问：每个 Claude 会话现在用的模型和 effort 能感知到吗？能的话加到点小鱼出现的详情卡里。

**能。** 会话记录里每条 `assistant` 记录都带着（2026-10-14 实测 Claude Code 2.1.296）：

| 字段 | 含义 | 本机实测值 |
|---|---|---|
| `message.model` | 这一轮实际用的模型 id | `claude-fable-5-1` / `claude-opus-5-5` |
| `requestedModel` | 请求的模型（通常等于上面那个） | 同上 |
| `effort` | 会话级的 effort | `high` |
| `perTurnEffort` | 这一轮实际的 effort（`/effort` 临时改过时和会话级的不同） | `high` |
| `isSidechain` | 子代理的记录为 true | — |

详情卡的状态行现在是「**休息中 · Fable 5.1 · high · 已 5 小时 30 分**」：阶段 → 模型 → effort
→ 持续时间。没读到模型的会话（还没有第一轮回复、记录格式变了）一个字都不多。

**红线 / 不变量**

- 取**主对话**最近一轮的值：子代理（`isSidechain`）的记录跳过
  （`test_the_latest_main_conversation_turn_gives_the_model_and_effort`）。
- `perTurnEffort` 优先于 `effort`；`message.model` 没有时退到 `requestedModel`。
- 模型 id 认不出来就原样显示，不猜（`test_model_ids_get_readable_names`）。
- 状态行其余部分（阶段、等批准时的工具名、持续时间）原样（既有用例全过）。

## 二、修改文件说明

增删取自 `git diff 72dfcd9 --numstat`。

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/claude_session_info.py` | +24 / −1 | `SessionDetail` 加 `model` / `effort`；`parse_transcript_tail` 从 `assistant` 记录取这两个字段（列进「必须找齐」名单，与 `custom_title` 同一口径）；`model_label`（`claude-fable-5-1` → `Fable 5.1`）；`apply_transcript` 写进详情 |
| `pet/session_pet_ui.py` | +6 / −1 | `status_line` 在阶段后面接「模型 · effort」；卡片合并实时信息与读回来的详情时把这两个字段也带上（第一版漏了，用例抓到） |
| `tests/test_session_model_effort.py`（新增） | +93 / −0 | 5 条：主对话最近一轮、子代理不算、`perTurnEffort` 优先；字段缺失的退路；模型 id 的可读名；详情与状态行；真实卡片上显示 |

**未改动**：hook 脚本（这两个字段只在点开详情卡时从记录里读，不走每轮上报）；小鱼头顶
的标题；i18n 表（模型名与 effort 值本身是英文，中英一样）。

## 三、实现要点

**为什么从会话记录读而不是 hook 上报。** hook 只在回合边界触发，带不出模型；记录里每轮
都有，点开详情卡时读尾部 128 KB 本来就在做，顺手取两个字段。代价是「读到为止」：会话还
没有第一轮回复时显示不出来。

**`wanted` 名单。** 这两个字段列进了「找齐就提前收工」的名单。还没有 `assistant` 记录的
会话会把整段尾部扫完——与「没改过名的会话找 `custom_title`」一样，实测 2.2 ms（§四）。

**可读名。** `claude-<名字>-<主>-<次>[-日期]` → `名字 主.次`，首字母大写；别的格式原样。
不维护一张「id → 名字」的表，新模型发布也不用改代码。

## 四、性能分析

**方法**：一次性脚本，构造 514 KB / 1,202 行的尾部，n=30 取中位数。

| 指标 | 实测 | 归属 |
|---|---|---|
| 解析尾部，还没有 `assistant` 记录（整段扫完） | 2.2 ms | 点开详情卡 1 次，后台线程 |
| 解析尾部，末尾就有 `assistant` + `custom-title`（提前收工） | 2.25 ms | 同上 |
| `model_label` | 0.4 µs | 状态行刷新时 |

**结论**：没有稳态开销；每次点开详情卡的解析多了两个字段的判断，量级在微秒；没有新的
系统调用、网络、磁盘、线程（读记录那一次本来就有）；内存多两个短字符串。

## 五、实机运行记录

```text
本会话自己的记录（走 si.load，和详情卡同一条路）：model: claude-fable-5-1 -> Fable 5.1 | effort: high
另两份本机记录：assistant 记录 78 / 65 条，模型 claude-opus-5-5，effort / perTurnEffort 都是 high；
子代理记录 0 条（本机最近三份记录里）
真实字体渲染详情卡（编造的会话）：状态行「休息中 · Fable 5.1 · high · 已 5 小时 30 分」，450×212，没有换行与裁切
```

真实桌宠在提交后重启。

**没有验证的部分**

- 没有在真实桌面上点开小鱼的详情卡看；渲染用的是同一个控件。
- WSL 通道的会话没有单独试（同一个解析函数，记录格式一样）。
- `perTurnEffort` 与 `effort` 不同的情形本机没有样本，只有用例。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests`、`git diff --check` | 通过 |
| 红 → 绿 | `pytest -q tests/test_session_model_effort.py` | 实现前 `5 failed`；实现后剩 1 条红（卡片合并详情时漏了新字段），补上后 `5 passed` |
| 聚焦 + 相关 | 新文件 + `test_session_pet_details` `test_session_custom_title` `test_session_card_themes` `test_overlay_session_pets` `test_island_session_history` `test_island_english` | 145 passed |
| 受影响时序族满载 3 遍 | — | 不适用：没有新增线程或等待 |
| 全量 | `python -m pytest -q -p no:cacheprovider`（隔离 worktree，`72dfcd9` 加本改动） | `5 failed, 5192 passed, 11 skipped in 437.29s`，5 个就是这台机器固定的环境性失败。这次运行之后只改了本报告与索引登记 |

## 七、已知限制与后续

- 只在详情卡上显示；小鱼头顶和灵动岛的会话清单没有加（那两处空间小）。
- 显示的是「最近一轮」的值；会话刚 `/model` 切换、还没发过消息时，显示的仍是上一轮的。
- 英文模式下这一行的「休息中 / 已 N 分钟」仍是中文（详情卡不在 i18n 第一片里）。

## 八、风险与回滚

- **影响面**：详情卡的状态行多一段；没读到时与原来相同。
- **配置 / 落盘**：无。
- **回滚**：`git revert` 后重启桌宠。
