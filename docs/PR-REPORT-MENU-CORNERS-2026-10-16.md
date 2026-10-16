# PR 报告：右键菜单圆角四角发黑（Windows 淡入结束后分层窗口被摘掉）

> **基线**：`44c2482`（feat(i18n): 右键菜单英文化）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-16
> **范围**：4 个文件（实现 2、测试 2）+ 本报告 + 2 张截图
> **关联**：[`PR-REPORT-MENU-ENGLISH-2026-10-16.md`](PR-REPORT-MENU-ENGLISH-2026-10-16.md)（顺手补的一条：旧编排里的「桌宠控制」没跟语言）

## 一、核心特性

用户 2026-10-16：「for the right click 右键菜单, as you can see on the 4 corners, there are black edge. I think this is because
the UI try to use smooth round corners, but not work it perfectly.」

**根因**（不是圆角画得不圆，是窗口在淡入结束后失去了逐像素透明）：

- Windows 平台插件只给两种窗口 `WS_EX_LAYERED`（`qwindowswindow.cpp` `setWindowLayered`）：「surface 带 alpha **且**
  `FramelessWindowHint`」，或「窗口不透明度 < 1」。
- `QMenu` 的窗口类型是 `Qt.Popup`，flags 里没有 Frameless 位。新版样式虽然设了 `WA_TranslucentBackground`（surface 有 alpha），
  但只在 Qt 的菜单淡入动画（`UI_FadeMenu`，不透明度从 0 → 1）期间满足第二个条件。淡入一结束 `setWindowOpacity(1.0)`，
  Qt 重新判定「不需要分层」并摘掉 `WS_EX_LAYERED`，圆角以外的透明像素就按不透明窗口合成——黑色。
- 时间线实测（真实配置，弹出后读 `GetWindowLongW(hwnd, GWL_EXSTYLE)`）：t=50 ms 分层 / 不透明度 0.57；t=200 ms 起不分层 /
  不透明度 1.0。之前的探针都是弹出后立刻抓屏（还在淡入里）才一直看不到黑角。
- 和「半透明菜单」开关无关：默认外观（半透明开）淡入后同样 585 个黑像素；用户的外观（半透明关、圆角 18）196～463 个。

**修法**：新版样式给菜单（以及经 `inherit_menu_style` 继承样式的每级子菜单）加 `FramelessWindowHint`。它对弹出菜单没有别的
可见影响（本来就没有边框），但让 Qt 在淡入前后都把它当分层窗口。

| | 主菜单黑像素（四角各 18×18） | 子菜单 | `WS_EX_LAYERED`（淡入后） |
|---|---|---|---|
| 改动前 | 196 | 202 | False |
| 改动后 | 0～1（阴影边缘） | 0 | True |

**顺手**：用户在 `94b42b7`（「桌宠」统一改叫「肥鱼」）之前保存的菜单编排里，子菜单名还是「桌宠控制」。`default_label` 只认
「肥鱼控制」是模板原名，于是英文菜单里这一项仍显示中文（用户截图里可见）。现在模板出现过的原名都算原名、都跟界面语言。

## 二、修改文件说明

| 文件 | 增删 | 改动 |
|---|---|---|
| `pet/context_menus/menu_styles/modern.py` | +6 / −0 | `apply_modern_menu_style` 在设 `WA_TranslucentBackground` 之后 `setWindowFlag(FramelessWindowHint, True)`，注释写明 Windows 分层窗口的判定条件与淡入时序。子菜单经 `inherit_menu_style` 走同一函数，自动覆盖。 |
| `pet/context_menus/registry.py` | +5 / −3 | `SUBMENU_LABEL_KEYS` 的值从「单个原名」改成「原名元组」：`pet_controls` 认「肥鱼控制」「桌宠控制」；`default_label` 按 `label in known[0]` 判断。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_desktop_pet_features.py` | +25 / −0 | `test_modern_menu_window_stays_per_pixel_alpha_after_the_fade_in`：新版样式下主菜单与继承样式的子菜单都有 `WA_TranslucentBackground` + `FramelessWindowHint`，且仍是 `Popup`。docstring 记录根因。 |
| `tests/test_menu_english.py` | +3 / −0 | `default_label` 对「桌宠控制」：英文 → Fish controls，中文 → 肥鱼控制；用户改过名的仍原样。 |

### 未改动

- 旧版模板（`legacy.py`，`WA_TranslucentBackground=False`、直角）不受影响。
- 外观设置（半透明 / 不透明度 / 圆角）语义不变，无配置迁移。
- 淡入动画保留（试过关掉 `UI_FadeMenu`：没用，黑角照旧，因为问题在稳态而不在动画）。

## 三、实现要点

- 诊断靠的是**时间线**：弹出后 0 / 50 / 200 / 400 / 700 / 1000 ms 分别读 `WS_EX_LAYERED`、`format().hasAlpha()`、`windowOpacity()`。
  属性一直是 True、alpha 一直有，只有分层样式在不透明度回到 1.0 的那一刻消失——直接指向 `setWindowLayered` 的三元条件。
- 三个候选逐个实测：加 Frameless（0～4 px）、关淡入（196 px，无效）、DWM `DWMWA_WINDOW_CORNER_PREFERENCE`（之前试过，无效）。

## 四、性能分析

| 指标 | 改动前 | 改动后 | 说明 |
|---|---|---|---|
| 建一次完整右键菜单（真实配置，20 次中位数） | 25.7 ms | 27.2 ms | 同一噪声区间（min 23.4 / 22.9 ms，max 受首帧字体加载影响 256～279 ms） |
| 新增调用 | — | 每级菜单 1 次 `setWindowFlag`（建菜单时，native 窗口尚未创建，不触发重建） | 每次右键 |

**结论**：① 稳态零开销（菜单不弹出时没有任何代码跑）；② 每次右键多 1～10 次 `setWindowFlag`（主菜单 + 各子菜单），
在 25 ms 的建菜单成本里测不出；③ 无新系统调用 / 网络 / 磁盘 / 线程——分层窗口本来在淡入期间就已经是分层的，
现在只是不再在淡入后切换回非分层，反而省掉一次 `SetWindowLong` + `InvalidateRect`；④ 内存无增长。

**环境**：Windows 11 Pro 26300，PySide6 / Qt 6.12，三屏 125%，`QT_QPA_PLATFORM=windows`，`.venv` Python 3.13。

## 五、实机运行记录

- **复现**（用户真实 `config.json` 建壳，弹出后 700 ms 抓屏幕合成结果）：`main: layered=False dark corner px=196`、
  `submenu: layered=False dark corner px=202`；更早一轮 `live-cfg-as-is.png` 463 px。截图
  `docs/screenshots/menu-corners-2026-10-16/menu-before.png`：四角可见黑色缺口，且「桌宠控制」一项仍是中文。
- **时间线**：`t=50 layered True opacity 0.57` → `t=200 layered False opacity 1.0`（真实、默认、半透明三种外观一致）。
- **修后**：`real/as-is: layered=True dark corner px=0`、`default/as-is: 4`（阴影边缘像素）、`main: 1`、`submenu: 0`。
  截图 `docs/screenshots/menu-corners-2026-10-16/menu-after.png`：四角干净，「Fish controls」已英文。
- **红灯**：两个新测试在改动前运行——`test_modern_menu_window_stays_per_pixel_alpha_after_the_fade_in` 在
  `windowFlags() & FramelessWindowHint` 断言失败；`test_registry_tables_follow_the_language` 在「桌宠控制 → Fish controls」断言失败。改后绿。
- 肥鱼已按常规方法重启（结束不含 `--settings` 的主进程，`run.bat` 拉起），右键即可看到效果；本机没有能点真实菜单的
  自动化工具（合成右键事件打不开菜单），上面的像素计数来自同一套样式代码在真实平台插件上的弹出窗口。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `ruff check pet tests` | All checks passed |
| 聚焦 + 相关 | `pytest -q tests/test_menu_english.py tests/test_desktop_pet_features.py tests/test_menu_layout.py tests/test_sprite_menu_parity.py tests/test_context_menu_lifecycle.py tests/test_context_menu_position.py tests/test_menu_tree_release.py tests/test_i18n.py` | 214 通过，1 失败 = 既有基线（图片目录选择器路径超 260） |
| 全量 | 未跑 | 改动是一个样式函数里的一个窗口标志位 + 一个标签判定，不涉及共享模型 / 配置迁移 / 生命周期 / 线程 / 打包 / 平台分支；按 AGENTS.md 的「局部展示 token」豁免。 |

## 七、已知限制与后续

- 黑角的四角计数在「阴影边缘」处允许 0～4 px，是阴影渐变最深处落在 18×18 采样框里，不是缺口。
- 若以后把菜单换成 OpenGL / RHI 表面（`accelerated`），Qt 的分层路径不同，要重新验证。

## 八、风险与回滚

- `git revert` 即可，无配置迁移。
- 风险点：`FramelessWindowHint` 理论上会影响 Qt 对窗口 `WS_POPUP` 样式的判定；实测弹出位置、阴影、子菜单展开、点击关闭
  都和原来一致（相关族 214 例通过）。
