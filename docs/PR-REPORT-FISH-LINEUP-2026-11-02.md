# PR 报告：「列队」——小肥鱼到主屏底边按状态从左到右站成一排

> **基线**：`ab6f4049`（`feature/session-fish-persist` 分支尖，PR #13；本 PR 叠在它上面，因为排序要用冻结状态）
> **分支**：`feature/fish-lineup`　**日期**：2026-11-02
> **范围**：14 个文件（实现 10、测试 4）
> **关联**：[`PR-REPORT-SESSION-FISH-PERSIST-2026-11-02.md`](PR-REPORT-SESSION-FISH-PERSIST-2026-11-02.md)（冻结鱼 / 上限）、
> [`PR-REPORT-CLAUDE-CODE-SESSION-FISH-2026-10-11.md`](PR-REPORT-CLAUDE-CODE-SESSION-FISH-2026-10-11.md)（「护驾」的落点与飞行段）

## 一、核心特性

用户 2026-11-02：「护驾」下面加一个「列队」——点一下，所有小肥鱼在主屏上**从左到右排成一队**，按状态分组，
同一状态里**最近更新的在最前**。开着 20 个会话时这是找鱼的办法：要人看的在队头。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 主肥鱼右键菜单「列队」，紧跟「护驾」 | 新版模板放在 `rally_pets` 后面（`modern-default-v1.json`），旧版模板同位；只有主肥鱼的菜单有；没有小肥鱼时置灰，提示同「护驾」 |
| 2 | 排序 | 状态档：等你批准 / 等你回复 → 工作中 → 休息中 → 冻结 → 手动生的小肥鱼；同档按「最近更新」倒序（活会话 = 当前阶段的起点 `since`；冻结鱼 = 历史里最后活动时间；手动生的保持现有先后） |
| 3 | 落点 | 主屏（合成窗那块屏）可用区底边，脚底贴底边、从左到右，鱼之间留 12 px；撞到主肥鱼或灵动岛就让到它右侧；一排站满往上再排一排（下一排底边在这一排最高那只头顶上方 12 px）；排到屏幕顶还站不下的留在原地 |
| 4 | 飞行 | 复用「护驾」的 `SpriteRallyWorld`（悬空动画、途中不碰撞、先快后慢落地），锚换成钉在原点的 `FixedAnchor`——护驾的落点跟着主肥鱼走，列队的落点是屏上的绝对位置 |
| 5 | 多屏 | 住在别的屏上的小肥鱼先搬回主屏（边界 / DPR 跟着换），与护驾一致 |

## 二、修改文件说明

| 文件 | 改了什么 | 为什么 |
|---|---|---|
| `pet/sprite_rally.py` | `lineup_spots(sizes, bounds, obstacles, gap)` 纯函数；`FixedAnchor` | 落点算法独立可测；飞行段原样复用，只差一个不动的锚 |
| `pet/overlay_session_pets.py` | `LINEUP_RANK`、`lineup_rank(sprite) -> (状态档, 最近更新秒) \| None` | 状态与时间都在控制器手里（含冻结鱼的历史行） |
| `pet/overlay_shell.py` | `lineup_pets()`：搬屏 → 排序 → `lineup_spots` → `_rally.start(FixedAnchor(), moves)`；一条 INFO 日志 | 与 `rally_pets` 平行的壳接线 |
| `pet/sprite_menu_facade.py` | `on_lineup_pets` 属性（主肥鱼才有） | registry 的可用性判断靠它 |
| `pet/context_menus/shared.py`、`registry.py`、`legacy.py` | `add_lineup_pets`；`lineup_pets` 的标签 / 图标 / `MenuActionSpec`（置灰条件同护驾）；旧版模板在护驾后加一行 | 两套模板都有入口 |
| `pet/menu_templates/modern-default-v1.json` | `lineup_pets` 节点紧跟 `rally_pets` | 用户要「在护驾下面」 |
| `pet/locale/zh.json`、`en.json` | `menu.shared.lineup`、`menu.action.lineup_pets`（列队 / Line up） | 文案 |
| `tests/test_sprite_rally.py` | 5 条：按序从左到右贴底边、让过主肥鱼、换排、屏满放弃、固定锚落到绝对位置 | 纯函数 |
| `tests/test_overlay_rally.py` | 4 条：状态 + 时间排序且换排后再从左起、没鱼不动、注册为「列队」、主肥鱼菜单紧跟「护驾」且小肥鱼没有 | 壳接线 |
| `tests/test_menu_layout.py`、`tests/test_sprite_menu_parity.py` | 默认布局清单 / 渲染清单多 `lineup_pets`；并列项允许「列队」 | 快照跟上 |

### 未改动

碰撞、拖拽、会话小鱼的生灭 / 认领 / 冻结语义、设置页。

## 三、实现要点

- **排序键放控制器**：`lineup_rank` 对活会话读 `_sessions[key]["phase"]` 与 `since(key)`（当前阶段的起点，与详情卡「从什么时候开始」同源），对冻结鱼读历史行的 `last_seen`。「等你回复」（回合结束还没去看）与「等你批准」同档——都是要人看的。
- **换排**：`lineup_spots` 维护当前排的底边与最高高度，`x + w + gap > right` 就把底边抬到「这一排最高那只头顶 + gap」再从左起；撞障碍只往右挪，不换排——障碍右侧放不下自然触发换排。每只鱼的尝试次数有上限（10 000），每次要么落下、要么 x 右移、要么换排，有限步。
- **固定锚**：`SpriteRallyWorld._Flight` 每 tick 读 `anchor.pos`，护驾用主肥鱼本体；列队传 `FixedAnchor()`（`pos = (0, 0)`），偏移即绝对落点。
- **测试里的替身素材**整张画布都是身体（544 px 宽），5 只一排站不下——正好测到换排。

## 四、性能分析

| 路径 | 实测 | 说明 |
|---|---|---|
| `lineup_spots`，20 只，2 个障碍 | **0.017 ms / 次** | `timeit` 200 次取均值（本机，.venv Python 3.13） |
| `lineup_spots`，40 只（硬顶） | **0.031 ms / 次** | 同上 |
| 飞行段 | 与护驾相同（每 tick 对每只在飞的鱼做一次插值），≤ 1.1 s 后结束 | 没有新的控制器，`SpriteRallyWorld` 复用 |

- 稳态开销：0——不点菜单什么都不发生；没有新线程、新定时器、新系统调用、新磁盘 / 网络访问。
- 触发频率：用户点一次菜单一次。
- 内存：`lineup_spots` 的临时列表随鱼数线性，调用完即释放。

## 五、实机运行记录

1. **测试**：9 条新测试先红后绿（函数 / 菜单项不存在即红）；相关族（护驾纯函数 / 护驾壳 / 菜单布局 / 菜单并列 / 英文菜单 /
   启动器 / 门面 / 会话小鱼 / i18n / 上下文菜单各族）**251 passed**；`ruff check pet/ tests/` 过。
2. **实机**：见文末「实机补记」——改动 cherry-pick 到本地运行分支后重启桌宠，看日志；菜单上的「列队」由用户点（我没法替用户点右键菜单，
   日志里 `列队：N 只出发` 那一行是点下去的凭据）。

### 实机补记（2026-11-02 19:18）

提交 `3e25bcde` cherry-pick 到本地运行分支（`local/run-with-toast-fix`，只有 `docs/INDEX.md` 冲突、取本分支版本），重启桌宠
（pid 51300）：启动日志 **0 条 ERROR**；3 s 内认领 18 个开着的会话，18 只活鱼 + 2 只冻结在场（上限 20）；主肥鱼右键菜单的
「列队」由用户点——点下去日志会多一行 `列队：N 只出发（共 M 只，K 只站不下留在原地）`，结果请用户回报后补进来。

## 六、已知限制与后续

- 列队是一次性的：鱼落地后照常游走 / 被碰撞推开，不会一直保持队形。
- 排序只认会话小鱼的状态；手动生的小肥鱼一律排最后、按现有先后。
- 没有「按项目分组」之类的第二维度；用户要再说。

## 七、风险与回滚

- 只加了一个菜单项和一个壳方法，没有改既有行为；回滚 = revert 这一个提交。

## 数字

| 文件 | +/− |
|---|---|
| `pet/sprite_rally.py` | 47 / 0 |
| `pet/overlay_shell.py` | 44 / 0 |
| `pet/overlay_session_pets.py` | 14 / 0 |
| `pet/context_menus/shared.py` | 14 / 0 |
| `pet/context_menus/registry.py` | 9 / 2 |
| `pet/sprite_menu_facade.py` | 6 / 0 |
| `pet/context_menus/legacy.py`、`pet/locale/zh.json`、`en.json` | 2 / 0 ×3 |
| `pet/menu_templates/modern-default-v1.json` | 1 / 0 |
| `tests/test_overlay_rally.py` | 77 / 0 |
| `tests/test_sprite_rally.py` | 63 / 1 |
| `tests/test_menu_layout.py` | 5 / 1 |
| `tests/test_sprite_menu_parity.py` | 1 / 1 |

按 AGENTS.md 的风险门只跑焦点 + 相关族（局部 widget / 菜单项行为，接口、持久数据、生命周期、平台分派都没动），没重跑全量。
