# PR 报告：灵动岛「最近的对话」加置顶（2026-10-20）

> **基线**：`eff99da2`（fix(i18n): 设置里切换界面语言后运行中的肥鱼真正切过去）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-20
> **范围**：13 个文件（实现 6、测试 5、文档 2）
> **关联**：「最近的对话」折叠框本体见 `docs/PR-REPORT-UI-LANGUAGE-ISLAND-2026-10-14.md`（平铺卡片样式）与
> `pet/claude_session_history.py` 模块说明。

## 一、核心特性

用户看着岛上「最近的对话」列表说：想把某个对话**钉住**，让它一直排在最上面，直到自己取消。
之前列表只按最后活动时间排，正在盯的那个对话一旦别的会话有动静就被挤下去，还会在 7 天后过期、
30 条上限时被挤掉。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 右键「置顶」 | 行的右键菜单第一项是「置顶」；置顶后那一项变「取消置顶」。中英文都有。 |
| 2 | 一直排最前 | 置顶的行排在所有没置顶的前面；几条都置顶时，置顶的之间仍按最后活动时间。 |
| 3 | 不过期、不被挤掉 | 置顶的行不受「保留 N 天」限制；排在最前，所以条数上限挤的永远是队尾没置顶的。取消置顶后立刻按原规则走（早过期的会马上消失）。 |
| 4 | 看得出来 | 置顶的行标题右边一枚主题色（accent）图钉，与右键菜单里 `context_menus.icons` 的 `pin` 同形；悬停提示「取消置顶」。没置顶的行不占那个位置。 |
| 5 | 记得住 | `pinned` 随历史文件 `claude-session-history.json` 落盘；重启后还在。旧文件没有这个键 = 没置顶。 |
| 6 | 再打开不丢 | 置顶的会话再次打开（`record` 更新标题 / 时间）仍是置顶。 |

**红线 / 不变量**：历史文件仍**只存路径、标题、入口**这类信息，不存对话内容（`test_file_holds_paths_and_titles_only`
把 `pinned` 加进白名单，其余不变）；没置顶的行排序、过期、上限规则与之前完全一样；点一行、其余菜单项的行为不变。

## 二、修改文件说明

增删行数来自只含本项工作 hunk 的补丁。**注意**：同一工作区里另一个会话 11:10 的提交 `e238e268`（Slack 关注页）整文件 `git add` 时把本项工作在 `pet/app.py`（+4/−1）、`pet/locale/zh.json`、`pet/locale/en.json`（各 +2）和 `docs/INDEX.md`（+1 行登记）里的改动一并带了进去；这四处没有再单独提交，本 PR 的提交只含其余 8 个文件和本报告。评审这四处请看 `e238e268` 里含 `pinned` / `history.menu.pin` / `HISTORY-PIN` 的 hunk。

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/claude_session_history.py` | +21 / −5 | `HistoryEntry` 加 `pinned: bool = False`；`SessionHistory.set_pinned(key, pinned) -> bool`（没这一行或没变化返回 False，不触发落盘）；`_prune` 过期只删没置顶的，排序键改成 `(not pinned, -last_seen)`；`load` 读回 `pinned`（只认 `True`）；`save` 经 `asdict` 自然带上。模块说明补一句。 |
| `pet/session_history_service.py` | +7 / −0 | `SessionHistoryService.set_pinned`：转给 store，有变化就 `_touched()`（发 `changed` + 3 秒后落盘），与 `remove` 同一条路。 |
| `pet/island_history_panel.py` | +60 / −10 | 菜单：`_PIN_ITEMS` 按行的置顶状态二选一放在第一项，后面一道分隔线再接原来的项；`_is_pinned(key)` 从当前行数据里查。行：加 `pin` QLabel（网格第 2 列，`ago` 挪到第 3 列，路径跨 1–3 列），没置顶时 `hide()` 不占位；标题省略宽度扣掉图钉。`pin_pixmap(widget, color, size)` 自己画图钉（不走 `vector_widget_icon`，那套颜色跟调色板走而岛的文字色是自己定的），按（颜色, 尺寸, DPR）缓存。 |
| `pet/app.py` | +4 / −1 | `_push_island_history` 行数据带 `"pinned"`；`_on_island_history_action` 认 `pin` / `unpin`，直接调服务的 `set_pinned`，不走「点一行」那套动作。 |
| `pet/locale/zh.json` | +2 / −0 | `history.menu.pin`「置顶」、`history.menu.unpin`「取消置顶」。 |
| `pet/locale/en.json` | +2 / −0 | `Pin to top` / `Unpin`。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_claude_session_history.py` | +64 / −1 | 置顶排最前、几条置顶之间按时间、取消置顶归位；再打开仍置顶；置顶的不过期、不被上限挤掉，取消后立刻按规则走；`pinned` 落盘往返；白名单加 `pinned`。 |
| `tests/test_session_history_service.py` | +18 / −0 | 服务层 `set_pinned` 发 `changed`、起落盘计时器、`flush` 后读回；没变化 / 不存在的行不发。 |
| `tests/test_island_history_panel.py` | +29 / −2 | 菜单第一项「置顶」发 `pin`，置顶行变「取消置顶」发 `unpin`，不认识的行按没置顶；置顶行有图钉、没置顶行不占位、复用行控件时图钉跟着数据走、标题不溢出。 |
| `tests/test_island_session_history.py` | +20 / −0 | AppShell 接线：右键 `pin` 后那一行排最前、行数据 `pinned=True`、不走 `run()`；`unpin` 后按时间归位。 |
| `tests/test_island_english.py` | +2 / −2 | 英文菜单第一项 `Pin to top`。 |

### 文档

| 文件 | 改动 |
|---|---|
| `docs/PR-REPORT-HISTORY-PIN-2026-10-20.md` | 本报告（新增）。 |
| `docs/INDEX.md` | +1 行：PR 报告存档登记。 |

### 未改动

- `pet/dynamic_island.py`：`set_session_history` 只是把行透传给面板，不用动。
- 设置页：没有新设置项——置顶是列表里每一行自己的状态，不是全局开关。
- `pet/context_menus/icons.py` 的 `pin` 图标：形状照抄，没改它。

## 三、实现要点

- **排序归数据层**。界面只画 `pinned`，不自己排；`_prune` 一处决定「置顶在前、各自按时间」。这样服务层
  `set_pinned` 之后发一次 `changed`，AppShell 重推行数据，面板 `set_rows` 按新顺序刷新，和「移除」走的是同一条链。
- **置顶不过期、不被挤**。过期只删 `not pinned` 的；上限仍是 `listed[:max_entries]`——置顶的排在最前，
  所以被切掉的永远是队尾没置顶的。极端情况（置顶的比上限还多）置顶的也会被切，上限最小 1、最大 200，实际不会碰到。
- **`set_pinned` 报「有没有变化」**。和 `record` / `remove` 一样：没变化就不发信号、不落盘，重复点菜单不写盘。
- **图钉自己画并缓存**。`vector_widget_icon` 的颜色跟控件调色板走（或 `menuStyle` 固定灰），而岛的文字色
  是配置里定的；所以复制那 5 笔路径按 accent 色画，按（颜色, 尺寸, DPR）缓存——每次 `_refill` 都要给置顶的行重设 pixmap。
- **菜单第一项二选一**。`_PIN_ITEMS[self._is_pinned(key)]`；状态从面板当前的 `_rows` 查，不另存。

## 四、性能分析

**方法（可复现）**：`PYTHONIOENCODING=utf-8 python <scratchpad>/bench_pin.py <repo>`（脚本见本报告末尾附录），
`QT_QPA_PLATFORM=offscreen`，每项 5 组取中位数。环境：Windows 11 Pro 26300，Python 3.13.15，PySide6（仓库 `.venv`）。

| 指标 | 实测 | 归属 |
|---|---|---|
| `entries()` 30 条、0 置顶 | 5.2 µs / 次（5 × 2000） | 既有热路径（每次 `changed` / 展开卡片各一次） |
| `entries()` 30 条、3 置顶 | 6.3 µs / 次 | 排序键从 `last_seen` 变成元组：+1.1 µs |
| `entries()` 200 条（上限）、0 / 20 置顶 | 29.3 / 31.7 µs | 同上，+2.4 µs |
| `set_pinned` 来回切 | 0.2 µs / 次 | 新增路径；只在用户点菜单时跑 |
| `panel.set_rows` 30 行、0 置顶（行数不变、内容变） | 3.03 ms / 次（5 × 100） | 既有热路径 |
| `panel.set_rows` 30 行、5 置顶 | 2.98 ms / 次 | 加缓存后与 0 置顶持平（缓存前 4.37 ms：每行重画 pixmap + show/hide 布局） |
| `pin_pixmap` | 39.4 µs 首次 → 0.5 µs 命中缓存 | 新增；每种（颜色, 尺寸, DPR）只画一次 |

**结论**：① 稳态开销：排序键变元组，`entries()` 每次 +1～2 µs，它每次 `changed` / 展开卡片才跑一次，可忽略；
面板刷新 30 行 ≈ 3 ms 与改前持平（`set_rows` 的成本本来就在 QLabel 省略文字和布局上）。② 新增路径：`set_pinned`
0.2 µs，只在点菜单时触发一次；图钉绘制每种颜色一次 ≈ 40 µs，之后 0.5 µs。③ 没有新的系统调用 / 网络 / 线程；
磁盘：置顶 / 取消置顶与「移除」一样走 3 秒延时落盘，一次用户操作最多多写一次历史文件（30 条 ≈ 8 KB）。
④ 内存：每条记录多一个 bool；图钉缓存每种（颜色, 尺寸, DPR）一张 12×12 @DPR 的 pixmap（125% 缩放下 15×15 px，< 1 KB），
岛换配色才多一张。

## 五、实机运行记录

- **前提复现**：用户截图里「Recent chats (30)」按时间排，「桌面肥鱼与 WSL 中 Claude 的对话」只因为是
  Live 才在最上面；真实历史文件 `%APPDATA%\big-fat-fish\claude-session-history.json` 改前 30 条、
  没有 `pinned` 键。
- **带新代码重启桌宠**（2026-10-20 11:07）：结束 `BigFish.exe -m pet`（pid 45604，10:58 起的），
  `Start-Process cmd.exe /c C:\Users\<me>\Github\BigFatFish\run.bat`；`pet-overlay-gate.log` 新增
  `11:07:41 acquired pid=26836`。新进程日志 `pet-26836.log` 19 行，无 Traceback / ERROR（唯一一条 INFO
  是本地 TTS 不可用，与本改动无关）。
- **历史文件按新格式回写**：重启 14 秒后（11:07:55）历史文件被新代码重写，30 条全部带 `pinned: false`，
  `ui_open: true`（折叠框开着，与截图一致）。证明 `load` 读旧格式 → `save` 写新格式这条路在真实数据上走通。
- **边界**：`set_pinned` 对不存在的行 / 没变化的状态返回 False（测试覆盖）；旧格式文件没有 `pinned` 键按没置顶读入（上面实机就是这个情况）。
- **没能自动验证的**：右键菜单「置顶」这一下要在岛上点，我这边没有能驱动灵动岛右键菜单的探针
  （没有 computer-use 工具；岛是无边框置顶窗口，也没有给它做过 IPC）。请用户在岛上右键任一行 →「置顶」，
  确认：它跳到最上面、标题右边出现图钉、菜单变「取消置顶」；再看历史文件里那一条 `pinned: true`。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests` | All checks passed |
| 红→绿 | 先写 10 个新用例，改实现前 10 红（`set_pinned` 不存在、菜单少一项、行没有 `pin`）；改后全绿 | ✔ |
| 聚焦 + 相关 | `pytest -q tests/test_claude_session_history.py tests/test_session_history_service.py tests/test_island_history_panel.py tests/test_island_english.py tests/test_island_session_history.py tests/test_island_notifications.py tests/test_i18n.py tests/test_language_reload.py tests/test_host_icons.py` | 161 passed in 2.36 s |
| 受影响时序族 | 本改动不碰线程 / 真实事件循环时序（服务层只是多一个同步方法），没有时序族要复跑 | 豁免，理由如左 |
| 全量 | 在隔离 worktree `C:\Users\<me>\wt-pin`（HEAD + 只含本项工作的补丁，`.venv` 解释器，`APPDATA` 指临时目录，`-X faulthandler`） | 见下 |
| 架构红线 | `tests/test_architecture.py` 在全量里 | 见下 |

全量结果：`4 failed, 5494 passed, 11 skipped in 616.85s (0:10:16)`，exit=1。4 个失败全是本机既有的环境性基线失败（`test_image_directory_picker_opens_right_drawer_with_three_column_masonry` 路径超 260；`test_festival_id_guard_survives_optimize`、`test_real_second_process_refused_on_overlay_topology` 子进程输出按 cp1252 解码；`test_capture_window_rect_coordinates_and_clamping` 多显示器负原点），与本改动无关；没有原生崩溃。`tests/test_architecture.py` 与 `tests/test_pr_report_discipline.py` 都在其中，通过。

## 七、已知限制与后续

- 置顶是「最近的对话」这个列表自己的状态，与会话小鱼、胶囊计数无关；不提供快捷键或拖动排序。
- 置顶的会话如果从 Claude Code 那边删掉了 transcript，这里仍会留着（它不过期）——用「从列表移除」清掉。
- 置顶的比条数上限还多时，最旧的置顶也会被切；上限最小 1，实际碰不到，没有专门处理。

## 八、风险与回滚

- 影响面：只有灵动岛「最近的对话」折叠框及其历史文件；没有新设置键。
- 历史文件多一个 `pinned` 键：旧代码读到会忽略（`load` 只取 `_FIELDS` 里的字符串字段），`git revert` 后不留残留状态，
  只是置顶信息会在旧代码下一次 `save` 时丢掉。
- 回滚：`git revert` 本提交即可。

## 第二轮（同日）：右键菜单被岛挡住 / 透明底看不清

用户试置顶时截图反馈：菜单在岛左侧弹出时是「透明底白字」浮在岛上看不清；在右侧弹出时是黑底白字，
但**在岛下面**，被岛挡住一截。

### 根因（Windows 实机探针，`scratchpad/probe_menu.py`）

| 现象 | 探针结果 | 原因 |
|---|---|---|
| 菜单在岛下面 | 弹出前后 `focusWindowChanged` 报了一个 `WindowType.Popup`；岛的 `_native_reassert_topmost` 被调 **2 次**；`GetWindow(GW_HWNDPREV)` 往上数，岛的 HWND 在菜单之上；菜单自己已是 `WS_EX_TOPMOST` | 岛的置顶保活把「本进程窗口获得焦点」和「应用变前台」都当成「别的 topmost 窗盖住了我」去重申；弹菜单恰好两条都触发，岛被插回菜单之上 |
| 透明底白字 | 面板是 `_card_box` 的子控件，`_card_box.setStyleSheet("background: transparent;")` 这种无选择器的样式表会继承给 `QMenu(self)` | 菜单没有自己的样式，底色跟着卡片透明；字色跟系统深色主题是白的 |

### 修法

| 文件 | 增删 | 改动 |
|---|---|---|
| `pet/dynamic_island.py` | +13 / −2 | `reassert_topmost`：`QApplication.activePopupWidget()` 不为 None（本进程有 Popup 开着）就返回 False——一道门挡住焦点 / 前台 / 30 秒心跳 / 点岛四条触发路径；`_on_own_window_focused` 另外对 `window.type() == Popup` 直接返回。`_sync_card_labels` 把 `context_menu_appearance` 传给两个面板。 |
| `pet/island_history_panel.py` | +21 / −2 | `style_island_menu(menu, primary, appearance)`：套 `apply_modern_menu_style`，`theme` 按岛的明暗（主文字色浅 = 深底岛 → 深色菜单）、`translucent=False`；`set_look` 多一个 `menu_appearance`；`row_menu` 末尾套样式。 |
| `pet/island_notification_panel.py` | +7 / −2 | 通知面板同一套（同样的 `QMenu(self)` 写法，同样的问题）。 |
| `tests/test_island_topmost.py` | +41 / −0 | 复现：弹出历史行菜单期间，焦点 / 前台 / 心跳 / 直接调用一律不重申；菜单收起后真正的 topmost 窗照旧重申。 |
| `tests/test_island_history_panel.py` | +18 / −0 | 菜单是 modern 样式、不透明底、随岛明暗切换、字号跟外观设置。 |
| `tests/test_island_notifications.py` | +8 / −0 | 通知菜单同一套。 |

红→绿：3 个新用例改实现前红（`modernDark` 属性不存在、弹菜单期间重申了 1 次），改后
`tests/test_island_topmost.py + test_island_history_panel.py + test_island_notifications.py + test_island_session_history.py` 78 过。

### 实机运行记录（第二轮）

- 探针修前：`reassert calls during popup: 2`，`island hwnd above menu: True`。
  只改焦点那条路后：`1`（弹菜单让应用变前台，`_on_application_state_changed` 又重申一次）、仍 `True`。
  加 `activePopupWidget` 门后：**`0`，`False`**。浅 / 深两种岛样式各跑一次，结果相同。
- 真实屏幕截图（`QScreen.grabWindow`，岛 + 菜单区域）：
  `docs/screenshots/island-menu-2026-10-20/menu_light.png`（浅岛：白底深字菜单压在岛上面）、
  `menu_dark.png`（深岛：深底浅字）。第一次抓浅岛时 600 ms 太早菜单还没画出来，改 1500 ms 后正常——
  抓图时机问题，不是产品问题。
- 桌宠重启两次（11:27 pid 14304 只带焦点那一条修法；11:28 pid 43636 带最终修法），
  `pet-43636.log` 无 Traceback（`ERROR` 唯一一次命中是 `<urlopen error timed out>` 那条 INFO）。
  岛上的真实右键仍请用户确认一眼。

### 性能（第二轮）

- `reassert_topmost` 多一次 `QApplication.activePopupWidget()`（读一个静态指针），每次心跳 / 焦点事件 +<1 µs。
- 菜单样式：`apply_modern_menu_style` 是肥鱼右键菜单每次弹出都在走的同一函数（建 2 个覆盖层 + 一份样式表），
  现在每次右键一行多跑一次；没有新线程 / 磁盘 / 网络。

### 全量（第二轮）

隔离 worktree `C:/Users/<me>/wt-menu`（HEAD `62efabb5` + 本轮补丁，`.venv` 解释器，临时 `APPDATA`，`-X faulthandler`）：`4 failed, 5511 passed, 11 skipped in 547.45s (0:09:07)`。4 个失败与第一轮完全相同，都是本机既有的环境性基线失败（路径超 260 / 子进程 cp1252 解码 ×2 / 多显示器负原点），没有原生崩溃。

## 附录：基准脚本

```python
# bench_pin.py <repo>
import os, statistics, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen"); sys.path.insert(0, sys.argv[1])
from pet.claude_session_history import SessionHistory

def bench(fn, repeat=2000):
    samples = []
    for _ in range(5):
        t0 = time.perf_counter()
        for _ in range(repeat):
            fn()
        samples.append((time.perf_counter() - t0) / repeat * 1e6)
    return f"median {statistics.median(samples):.1f} us (5 x {repeat}, min {min(samples):.1f})"

def make(n, pinned):
    h = SessionHistory(None, max_entries=200)
    for i in range(n):
        h.record("claude", f"{i:08d}-aaaa-4bbb-8ccc-000000000000", cwd=f"C:\\p{i}", seen=1.8e9 + i)
    for i in range(pinned):
        h.set_pinned(("claude", f"{i:08d}-aaaa-4bbb-8ccc-000000000000"), True)
    return h

for n, pinned in ((30, 0), (30, 3), (200, 0), (200, 20)):
    h = make(n, pinned); print(f"entries() n={n} pinned={pinned}: {bench(h.entries)}")

from PySide6.QtWidgets import QApplication
from pet.island_history_panel import SessionHistoryPanel, pin_pixmap
app = QApplication.instance() or QApplication([])
panel = SessionHistoryPanel(); panel.set_look(primary="#e5eaf5", secondary="#a0aabe", accent="#40b8ff", width=308); panel.set_open(True)
def rows(pinned, ago):
    return [{"key": ("claude", f"s{i}"), "label": f"chat {i}", "where": "终端", "host": "terminal",
             "path": f"C:\\work\\p{i}", "ago": ago, "live": i == 0, "pinned": i < pinned} for i in range(30)]
for pinned in (0, 5):
    flip = [0]
    def refill():
        flip[0] += 1; panel.set_rows(rows(pinned, f"{flip[0]} min ago"))
    print(f"panel.set_rows 30 rows pinned={pinned}: {bench(refill, repeat=100)}")
print(f"pin_pixmap: {bench(lambda: pin_pixmap(panel, '#40b8ff'))}")
```
