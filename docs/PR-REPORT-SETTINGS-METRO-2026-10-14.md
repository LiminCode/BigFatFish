# PR 报告：设置页改成 Windows Phone / Metro 风格——方角磁贴、上下折叠、朝光标倾斜（2026-10-14）

> **基线**：`71960c7`（feat(slack-watch): 设置页「自动化与联动」新一节，`feature/claude-session-fish`）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-14
> **范围**：15 个文件（实现 5、测试 5：新增 1、改 4、规范 1、文档 2、截图 4 个目录 31 张）
> **关联**：[`SETTINGS-REDESIGN-UI-ACCEPTANCE.md`](SETTINGS-REDESIGN-UI-ACCEPTANCE.md)（本轮追加了 iteration-10）、
> `.agents/skills/desktop-pet-ui-style/references/visual-system.md`（令牌与组件规范，本轮重写）

## 一、核心特性

**用户的要求**：设置界面改成 Windows Phone 的风格；页内不要左右 tab（「菜单」点开还有三个左右标签，不统一），
改成上下折叠；按钮和分区不要圆角，用磁贴；鼠标移到磁贴上最好有 Windows 那种轻微倾斜。风格的具体取舍由我定。

**定下的 Metro 口径**（令牌集中在 `pet/settings_theme_qss.py::METRO_TOKENS`）：

| 方面 | 以前 | 现在 |
|---|---|---|
| 圆角 | 卡片 12px、字段 7px、按钮 7px、披露头 10px、菜单 8px、侧栏 9px | **一律 0**（含弹出面板、滚动条、搜索框） |
| 卡片 | 白底 + 1px 描边 | **平铺磁贴**：没有描边、没有阴影，靠底色分层（浅 `#ffffff` on `#f2f2f2`；深 `#2a2a2f` on `#1b1b1f`） |
| 页标题 | 22px / 600 | **30px / 300**（大而轻） |
| 节标题 | 13px / 600 | 15px / 600 |
| 侧栏 | 浅灰带 + 右描边；选中浅灰圆角块 | 一整条深一点的带子、无描边；项是 38px 满宽条；**选中 = 主题色底白字 + 左缘 4px** |
| 按钮 | 白底 1px 描边 | **透明底 2px 描边、粗体**；悬停浅底，按下反色，焦点主题色 |
| 开关 | 圆形滑块的胶囊 | **44×20 方角**：描边轨道 + 12×20 竖条滑块，开着时轨道填主题色 |
| 页内同级任务 | 左右分段标签（菜单 3 个、互动 2 个） | **上下折叠的手风琴**：每个任务一块 44px 表头磁贴（展开时左缘主题色竖条、箭头朝下），一次只开一页 |
| 磁贴手感 | 无 | **朝光标倾斜**：悬停 ±4°、按下 ±8°，透视距离 900px；按钮、折叠表头、侧栏项都有 |

主题色仍是 `#0a84ff`，只给选中 / 焦点 / 开着的开关 / 展开的表头左缘。

**红线 / 不变量**：
- `SettingsTabContainer` 的类名、`objectName`（`settingsTaskTabs`）与 `addTab / keys / labels / currentKey /
  setCurrentKey / key_for_descendant / activate_for_descendant / stack` 口径不变：搜索深链、既有用例照旧；收起的页只是
  `hide`，对象与取值都在。
- 九个能力域、每个域里的节名、行 id 一个没动；保存链与配置格式不变。
- 倾斜是纯视觉：命中测试、布局、几何都不变；没有定时器、没有动画线程，只在鼠标事件里重画那一个控件。
- 非 Metro 的东西没碰：右键菜单、灵动岛、聊天窗、气泡各自的样式照旧。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/settings_theme_qss.py` | +186 / −322 | 重写：一张 `METRO_TOKENS` 表（明 / 暗各 17 个令牌）+ 一个模板，`metro_stylesheet(dark)` 生成；所有圆角归零、磁贴无描边、侧栏 / 按钮 / 页标题 / 折叠表头按上表；`QSplitter::handle` 透明；`_settings_stylesheet` 入口不变，旧名 `_LIGHT_SETTINGS_STYLESHEET` / `_DARK_OVERRIDE` 仍可 import。 |
| `pet/settings_widgets.py` | +272 / −98 | 新增 `tilt_transform`（纯几何）、`TiltButton`（在倾斜画布上用 `style().drawControl` 画 QSS 外观，`_paint_overlay` 钩子）、`TiltItemDelegate`（列表项倾斜 + `install`）；`ToggleSwitch` 改 Metro 方角；`ModernSelect` 方角；`SettingsDisclosureHeader` / `SettingsMenuButton` 改继承 `TiltButton`，箭头画在同一变换下（去掉了原来不会跟着倾斜的 `chevron` 子 QLabel）；`SettingsTabContainer` 改为手风琴（`_AccordionPages` 顶替 `stack`）；共享字段 / 弹出面板样式里的圆角归零；文件内几个 `QPushButton(` 换成 `TiltButton(`。 |
| `pet/modern_settings_dialog.py` | +7 / −5 | 侧栏装 `TiltItemDelegate`、项高 34 → 38；三个 `QPushButton(` 换 `TiltButton(`；去掉已不存在的 `_CurrentPageStack` import。 |
| `pet/settings_pet_controls.py` | +7 / −6 | 六个 `QPushButton(` 换 `TiltButton(`。 |
| `pet/settings_music.py` | +3 / −3 | 一个 `QPushButton(` 换 `TiltButton(`。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_settings_metro.py`（新） | +167 | 设置页 QSS（含共享字段与弹出面板）里没有任何非零圆角、`BROWSER_CONTROL_SPEC.radius == 0`；令牌落到 QSS（磁贴、侧栏、选中、页标题 30/300、表头左缘、按钮 2px 描边）；系统深色选深色表；`tilt_transform` 几何（None / 空矩形恒等、正中不偏、光标那一侧退得比对面多、按下更明显、光标跑出去角度有界）；`TiltButton` 跟着光标变且画得出来；折叠表头与菜单按钮是倾斜磁贴；侧栏装了代理、开了鼠标跟踪、项高 ≥ 38；开关 44×20、开着轨道中部主题色、滑块方角在右、关着只有描边；手风琴一次只开一页、收起的页不压最小宽度、`stack` 替身可用。 |
| `tests/test_menu_layout.py` | +26 / −11 | 页标题 22 → 30 且轻体、节标题 13 → 15；弹出面板圆角 10px → 0；「紧凑左对齐的分段标签」用例改写为「满宽磁贴的上下手风琴」（三块表头满宽、默认开第一块、点第三块切过去、再点开着的不收）。 |
| `tests/test_requested_regressions.py` | +12 / −8 | 深色 / 浅色样式表断言改按 `METRO_TOKENS`（页底色、文字色、按钮块里的文字色）。 |
| `tests/test_desktop_pet_features.py` | +3 / −3 | 侧栏「右描边 + `#f7f7f8`」改为「`#e6e6e8` 无描边」；`font-size: 22px` → `30px`。 |
| `tests/test_architecture.py` | +3 / −1 | 设置页行数预算 2403 → 2405（侧栏倾斜代理的 import 与 install 各 1 行）。 |

### 规范与文档

| 文件 | 增删 | 内容 |
|---|---|---|
| `.agents/skills/desktop-pet-ui-style/references/visual-system.md` | +73 / −47 | 重写为 Metro 口径：权威顺序、组成（手风琴）、字号表、间距表、表面与颜色表、「没有圆角」「倾斜」两节、组件清单、离屏截图没有中文字体的说明。 |
| `docs/SETTINGS-REDESIGN-UI-ACCEPTANCE.md` | 追加 | iteration-10 一节：证据目录、逐页结果、没做的。 |
| `docs/screenshots/settings-redesign/iteration-10-metro-{wide,dark,compact,real}/` | 31 张 | 离屏 1100 浅 / 深、720 浅各九页；真实窗口四张。 |

### 未改动

- `pet/settings_interaction.py`、`pet/settings_menu_layout_editor.py`、`pet/settings_*.py` 其余：行与控件照旧，只是落在新样式上。
- 右键菜单的圆角设置（`corner_radius`）与聊天主题：那是别的表面，不在本轮口径里。

## 三、实现要点

- **倾斜怎么做的**：`QTransform.rotate(angle, Qt.XAxis / YAxis, distance)` 是带透视的投影旋转。按光标到磁贴中心的相对位置
  算两根轴的角度（光标那一侧往屏幕里压；Qt 两根轴的正方向相反，符号实测定、用例守着），按下时角度翻倍再缩 1.5%。
  `TiltButton.paintEvent` 把这个变换设给 painter，再让 `style().drawControl(CE_PushButton)` 照常画——样式表怎么写
  就怎么出来，只是画布斜了；箭头之类的附件走 `_paint_overlay` 在同一变换下画。列表项用 `QStyledItemDelegate.paint`
  做同样的事（`TiltItemDelegate`），视口在鼠标移动时整体重画一次（0.3 ms，见性能）。
- **为什么不是 QGraphicsView**：真 3D 需要把控件搬进场景；这里要的只是「压一下」的反馈，painter 变换够用，
  且不改任何布局与命中。
- **手风琴保留旧 API**：既有两个族的用例、搜索深链（`activate_for_descendant`）、截图脚本都按 `SettingsTabContainer`
  的口径取页面，所以类名、`stack.currentWidget()` 等都原样保留，`_AccordionPages` 是个只读替身。表头改按 `toggled`
  而非 `clicked` 响应，这样截图脚本「全部展开」那种程序化 `setChecked(True)` 也会切到那一页；点开着的那块不收
  （否则整页空掉、`currentKey` 也没了意义）。
- **取舍**：没做 Metro 的全大写 / 全小写标题（中文没有大小写）；没做磁贴的「翻转 / 动态磁贴」；没做系统
  reduced-motion 的探测（Qt 没有现成 API，倾斜本身只有几度且不自动运动）。

## 四、性能分析

**方法（可复现）**：`QT_QPA_PLATFORM=offscreen .venv\Scripts\python.exe <探针>`，本机 Windows 11 Pro 26300、
Python 3.13.15、PySide6 6.12.0；样本见各行。

| 指标 | 实测 | 归属 |
|---|---|---|
| `tilt_transform` 一次 | 3.65 µs（20000 次均值） | 新增：每次鼠标移动算一次 |
| `QPushButton.grab()`（QSS，基线） | 中位 0.017 ms，p95 0.020 ms（300 次） | 既有 |
| `TiltButton.grab()` 未悬停 / 悬停倾斜 | 0.040 / 0.041 ms，p95 0.059 / 0.090 ms | 新增：多了一次 `QStyleOptionButton` 初始化与透视变换，绝对值 +0.02 ms |
| `SettingsDisclosureHeader.grab()` 平 / 倾斜 | 0.082 / 0.076 ms | 新增：含箭头 |
| 样式表生成 `_settings_stylesheet` | 0.03 ms，7855 字符 | 既有路径，字符数由 ~9.9k 降到 7.9k |
| 设置对话框建好并显示 | 401 ms（九页全建） | 既有路径（本轮没量基线；样式表只占 0.03 ms） |
| 侧栏视口整体重画（鼠标在侧栏里每移动一次） | 中位 0.31 ms（100 次） | 新增稳态：只在鼠标在侧栏里移动时发生 |

**结论**：
1. **稳态开销**：没有定时器、没有新线程；鼠标不动时零开销。鼠标在磁贴上移动时，那一个控件重画一次
   （0.04–0.08 ms）或侧栏视口重画一次（0.3 ms），都远低于一帧。
2. **新增路径**：倾斜几何 3.65 µs；单个按钮的绘制成本翻倍（0.017 → 0.040 ms），绝对值可忽略。
3. **系统调用 / 线程**：无新增。
4. **内存**：每个 `TiltButton` 多一个 `QPoint`；样式表更短。

## 五、实机运行记录

**环境**：本机 Windows 11 Pro（26300），三屏 125% 缩放，Qt `windows` 平台插件。

**真实窗口**（`shot_settings2.py`：在本进程里直接建 `ModernSettingsDialog(Config())`，真实字体、真实配置、不保存；
用 `SetCursorPos` 把光标放到磁贴上再 `grab()`）：四张在
`docs/screenshots/settings-redesign/iteration-10-metro-real/`：
- `01-常规-windows.png`：30px 轻体页标题、15px 节标题、白色磁贴铺在 `#f2f2f2` 上、Metro 开关（开 = 蓝轨 + 右侧黑滑块，关 = 描边 + 左侧滑块）、方角下拉；侧栏「常规」是主题色满宽条。
- `01-常规-悬停侧栏倾斜-windows.png`：光标在「菜单」项右下，那一项呈白色磁贴并朝右下压下去（梯形）。
- `04-菜单-手风琴-windows.png`：「菜单编排」表头展开（左缘蓝条、箭头朝下），下面是内容；「快捷启动」「外观」收在底部（箭头朝右）；排序 / 移动到 / 插入 / 自定义 / 更多是 2px 描边的方角按钮。
- `04-菜单-悬停表头倾斜-windows.png`：光标在「快捷启动」表头右侧，表头朝右压下去。

一开始按窗口标题找窗口拿到的是用户先前就开着的旧设置进程（旧代码、圆角、左右标签），截了三张旧的——于是改为
在本进程里建对话框。**那个旧的设置窗口我没有关**（可能有没保存的改动），它跑的是旧代码，要关掉重开才是新样子。

**离屏矩阵**（`scripts/capture_settings_pages.py`，1100×760 浅 / 深、720×760 浅，各九页）：
`iteration-10-metro-wide|dark|compact/`。离屏平台没有中文字体、文字是方块，只核布局与配色：深色磁贴 `#2a2a2f`
on `#1b1b1f`、分隔线、滚动条方角；720 px 下「互动」页手风琴表头满宽、控件不出框。

**测试**：
- 新增 `tests/test_settings_metro.py` 11 用例全绿；设置页相关族（菜单编排、互动标签、桌宠功能、既往回归、架构守卫、
  资源、音乐、Slack 关注、聊天主题、VS Code 工作区）`328 passed, 1 skipped, 1 failed`——那 1 个是这台机器固定的
  `image_directory_picker` 路径超 260 基线失败。
- `ruff check pet tests`、`git diff --check` 通过。
- 全量见本节末尾。

**没有验证的部分**：
- 真实窗口的深色模式（离屏有）、放大字体与极端文案矩阵（本轮没跑 `--font-scale 1.25 --extreme-copy`）。
- 真实的点击 / 按下态（倾斜加倍 + 按钮反色）只在离屏用例里验证了变换，没有截到真实按下的那一帧。
- macOS / Linux 上的样子：令牌与控件跨平台同一份，但真实外观只在 Windows 看过。

**全量结果**（隔离 worktree `bffv3` = 基线 `71960c7` + 本补丁，`python -m pytest -q -p no:cacheprovider`，
`QT_QPA_PLATFORM=offscreen`、`APPDATA` 指到临时目录）：

```
5 failed, 5271 passed, 11 skipped, 249 warnings in 494.69s (0:08:14)
```

4 个是这台机器上固定的环境性失败（`image_directory_picker` 路径超 260、`festival_id_guard` 子进程按 cp1252 打印中文、
`real_second_process`、`capture_window_rect` 多显示器负原点）。第 5 个 `test_modern_settings_panel_uses_sidebar_and_includes_ai_settings`
是本轮改的断言写成了只认浅色令牌：全量里前面的用例把应用调色板留成了深色，对话框建的是深色表（以前浅色基础表总在、
深色只是追加，所以老断言不受影响；现在两张表二选一）。改为明 / 暗任一令牌命中即可，单跑该文件通过。
