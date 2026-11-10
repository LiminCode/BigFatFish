# 会话记忆蒸馏：模型输出里坏掉一项时，不再静默丢掉后面的项

> **基线**：`3414c8d9`（main，第二期补进 main 的报告追记）
> **分支**：`fix/memory-distill-dropped-items`　**日期**：2026-11-10
> **范围**：7 个文件（实现 2、文案 2、测试 2、文档 1 + 索引）
> **关联**：[`PR-REPORT-MEMORY-DISTILL-PHASE2-LAND-2026-11-10.md`](PR-REPORT-MEMORY-DISTILL-PHASE2-LAND-2026-11-10.md)
> 第五节的观察、第七节的后续项

## 一、核心特性

11-10 实机蒸馏时模型写了 5 项提案，入库 4 项：有一项的字符串里带了没转义的直引号，整段不是合法 JSON。旧的抢救逻辑
是为「输出到顶被截断」写的——从末尾往回找最后一个能让前缀成为合法数组的 `}`——所以坏项**以及它后面的所有项**一起
丢掉，结果里 `truncated=False`、页面上没有任何提示，候选游标照常推进（那几条候选再也不会被送去蒸馏）。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 只丢坏的那一项 | 整段解析失败时逐项解析：解得出的留下，解不出的跳到下一个项边界接着解 |
| 2 | 看得见丢了几项 | `RunResult.dropped`、状态里的 `last_result.dropped`；手动总结后的状态行与「上次总结」那行都带一句说明 |
| 3 | 这批候选重送一次 | 丢了项就不推游标（`RunResult.resend`），下次总结整批再送；连着两次都丢就放行，不无限重送 |

**红线 / 不变量**：合法输出的解析结果与之前逐字相同；「输出到顶」的规则不变（游标推到这批的一半），末尾那半项仍算
截断、不算进丢项；一项都解不出来仍是「没按约定输出」、游标不动。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/memory_distill_run.py` | +67 / −24 | `_json_array` + `_salvage`（从后往前找 `}`）换成 `_array_body`（取数组那一段）/ `_recover`（逐项 `raw_decode`，失败跳到下一个 `}, {`）/ `_parse`（先整段、再逐项，返回 项 / 丢项数 / 是否断在末尾）；公开 `parse_array(text) -> (项, 丢项数)`，`_json_array` 留作薄封装。`RunResult` 加 `dropped` / `resend`。`run_once`：丢项数写进结果与 `last_result`；不是截断而有丢项、且上一次没有因丢项重送过（状态 `dropped_streak`）时不推 `last_candidate_time` |
| `pet/memory_distill_ui.py` | +10 / −1 | 新函数 `dropped_note(dropped, resend)`；`_on_distilled` 的状态行与 `run_line`（「上次总结」那行）在有丢项时追加一句 |
| `pet/locale/zh.json`、`pet/locale/en.json` | 各 +3 / −1 | 新文案 `distill.run.dropped` / `distill.run.dropped_resend`（−1 是上一行补逗号） |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_memory_distill_run.py` | +62 / −0 | 中间一项坏：只丢它、计数 1；中间坏 + 末尾断：计数 2；一项都救不回来是 `None`；`run_once` 丢项 → `resend`、游标不推、第二次还丢就放行、干净一次后额度恢复；截断不重复计入丢项 |
| `tests/test_memory_distill_phase2_ui.py` | +21 / −0 | 真实窗口点「现在总结」：坏项后面的提案进列表，状态行与「上次总结」行写明丢了 1 项；英文文案 |

### 未改动

`memory_distill_sink.py`、`memory_distill_service.py`、设置页：丢项只影响「解析 → 入提案库 → 游标」这一段。
`parse_proposals` 的字段校验（非法动作 / 空标题 / 重复）不算丢项——那是合法 JSON 里内容不合约定，行为不变。

## 三、实现要点

- **逐项解析而不是修 JSON**：不去猜哪个引号该转义（猜错会把内容改掉），坏项整项不要。`json.JSONDecoder.raw_decode`
  从每个项的 `{` 起解，失败就用 `\}\s*,\s*(?=\{)` 找下一个项边界。
- **计数宁少勿多**：坏项内部碰巧有 `}, {` 时会在它中间重试并再次失败，连续的失败只算一项。
- **为什么重送而不是照推游标**：坏掉的那项对应哪几条候选不知道；提案按 id（动作 + 作用域 + 项目 + 标题的哈希）去重，
  重送只会多花一次模型调用，不会产生重复提案。**为什么只重送一次**：同一批候选可能稳定诱发同样的坏输出（引用了
  带引号的原话），无限重送会让这批永远卡住、越积越大。
- **备选（没做）**：让模型重写坏项（多一轮调用、提示词更复杂）；改用结构化输出（服务商接口差异大，公司侧走
  `claude -p` 没有这个能力）。

## 四、性能分析

**方法**：对 20 项、约 11 KB 的输出各调 200 次 `parse_array` 取平均（`timeit`）。环境：Windows 11、Python 3.13、本机。

| 指标 | 实测 | 归属 |
|---|---|---|
| 合法输出（11,024 字符，20 项） | 62 µs / 次 | 既有路径（整段 `json.loads`，没变） |
| 中间坏一项（11,030 字符 → 19 项，丢 1） | 86 µs / 次 | 新增路径 |
| 末尾截断（7,349 字符 → 13 项） | 171 µs / 次 | 新增路径（替换旧的往回找 `}`） |

**结论**：① 稳态（合法输出）走的还是整段 `json.loads`，没有变化；`run_once` 里原来 `parse_proposals` 和
`_json_array` 各解析一次，现在仍是两次（`parse_proposals` + `_parse`）。② 新路径只在输出不合法时走，一次不到 0.2 ms，
而它前面的模型调用是几十到几百秒；触发频率 = 每次蒸馏最多一次（每日一次 + 手动）。③ 没有新的系统调用 / 网络 /
磁盘 / 线程；状态文件多两个键（`dropped_streak`、`last_result.dropped`），仍是原来那一次写。④ 内存没有增长。
重送会多一次模型调用（上限：每出现一次丢项多一次）。

## 五、实机运行记录

- **前提的现场证据**：11-10 13:58 的实机蒸馏（个人 key，真实候选）模型写 5 项、入库 4 项，状态里没有任何提示——记录在
  [`PR-REPORT-MEMORY-DISTILL-PHASE2-LAND-2026-11-10.md`](PR-REPORT-MEMORY-DISTILL-PHASE2-LAND-2026-11-10.md) 第五节。那次的
  模型原始输出没有落盘（`RunResult.raw_text` 只在内存里），所以无法拿原文重放。
- **本机跑过的**：上面性能一节的脚本在本机真实解释器里跑出的输出：

  ```
  valid: 11024 chars -> 20 items, dropped 0, 62 us/call
  one broken item: 11030 chars -> 19 items, dropped 1, 86 us/call
  truncated tail: 7349 chars -> 13 items, dropped 1, 171 us/call
  ```

- **为什么没有「真实模型吐出坏 JSON」的实机记录**：坏项是模型偶发的（11-10 那次是它在字符串里引了一句带直引号的话），
  不能按需触发；为了复现去反复调用个人 key 既花钱又会往用户的待审队列里塞提案。真实窗口路径由
  `test_page_says_how_many_items_the_model_garbled` 覆盖（真实 `MemoryDistillWindow` + 真实服务，只有模型是替身）。
- **后续的真实输出**：第三期公司侧的实机蒸馏（真实 `claude -p` 输出）走的是同一个 `_parse`，结果里的 `dropped` 会记在
  那一期的报告里。
- **用户可见行为**：要等桌宠从含本改动的 main 重启后才生效；重启记录随第三期最后一个 PR 一并补。

## 六、测试与验证

- **红 → 绿**：新增的 3 条 `test_memory_distill_run.py` 用例在改实现前全部失败（`parse_array` 不存在 /
  `RunResult` 没有 `dropped`），改后通过。
- `ruff check pet tests`：All checks passed。
- 蒸馏族 5 个文件：102 passed。
- 全量 pytest：见 PR 描述（合并前在隔离 worktree 里跑）。

## 七、已知限制与后续

- 两项连着都坏时只计 1 项（宁少勿多）。
- 模型原始输出仍不落盘；要事后分析坏输出得另加（会把候选原话写进又一个本地文件，暂不做）。
