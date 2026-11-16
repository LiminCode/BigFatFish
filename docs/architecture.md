# 架构与红线

> 进程里有哪些对象、两种渲染拓扑、多屏怎么分工，见 [`AGENTS.md`](../AGENTS.md) 的 Project shape（那是唯一的一份）。
> 本文记的是它没写的部分：分层、由测试守着的红线、Qt 生命周期规则、Windows 关机时的派生闸门。

## 分层与依赖方向

| 层 | 放什么 | 约束 |
|---|---|---|
| 纯逻辑 | 不需要界面就能测的函数与数据：`collision.py`、`physics.py`、`sprite_collision.py`、`speech_bubble_text.py`、`voice_chime.py`、各功能的 `*_run.py` / 解析模块 | 不 import Qt；网络库、`edge_tts` 这类重依赖也不进这一层 |
| 服务 | 调度、线程、IO、播放：`voice_chime_service.py`、`agent_link.py`、`proactive.py`、各 `*_service.py` | Qt 惰性导入；不继承 `QObject` 的服务由 `AppShell` 持有引用，否则会被回收 |
| 界面 | 窗口、设置、菜单、气泡、岛：`overlay_shell.py`、`modern_settings_dialog.py`、`context_menus/`、`island*.py` | 跨线程只经 queued 信号回 GUI 线程 |

新功能按这三层各放一个模块（参照 `voice_chime.py` / `voice_chime_service.py` / `voice_chime_settings.py`），
纯逻辑层先写先测。

## 红线（`tests/test_architecture.py` 守着）

| 红线 | 违反时怎么办 |
|---|---|
| 纯逻辑模块源码里不出现 `PySide6` | 把 Qt 相关的部分挪到服务层 |
| `decode_fanout.py` 不反向 import `pet.window` / `pet.webm_clip` | 钩子经属性注入 |
| 已退役的多进程多宠模块不存在、不被 import | 不要复活；多宠是进程内的 |
| `app.py` / `agent_link.py` / `context_menus/` 不访问 `win._xxx` | 在窗口上加公开 seam |
| `modern_settings_dialog.py` 模块顶层不 import `pet.chat.*` | 延迟到函数里 import（为无聊天变体留的，见 [上游](upstream.md)） |
| `settings_widgets.py`、`settings_styles*.qss` 不能存在却没人引用 | 删掉或接上 |
| `window.py`、`modern_settings_dialog.py` 行数不超预算 | 见下 |

**行数预算是绊线，不是目标。** 超了：先把新内容拆到独立模块；实在拆不动，把预算常量校准到实测值，
写上日期和理由。不要靠压行宽、合并语句、删注释塞回去。预算是**组合性质**：两个各自合规的 PR 合到一起
可能越线，合并前先算一遍（见 [开发指南](development.md) 的合并一节）。

## `window.py`：只修崩溃

`PetWindow` 只为推流（capture）界面和单宠旧路径保留，**新功能不加在这里**，加在 overlay 这一侧
（`PetSprite` / `OverlayShell` 和各控制器）。必须动它时：

- 拆分只做机械搬移，不夹带行为修改，回归才能归因。
- 控制器持有自己那个域的状态；需要窗口的常量在构造时注入，不在模块级 `import window`。
- 窗口保留同名的薄委托属性，既有调用和测试不用改。
- 信号直接连控制器的方法，不经窗口转发。

## 配置键、菜单项、设置行的登记

这几处都是「漏一处测试就红」的刻意设计：

- **新增顶层配置键**要改三处：`pet/config.py` 的默认值字典、`Config.reload()` 的白名单、
  `tests/test_config_schema.py` 的两个快照。白名单里没有的键，保存后读不回来。
  `version` / `proactive_screen` / `agent_link` / `chat` 走各自的合并路径，不进普通白名单。
  `config_domains.py` 只做取子键和聚合，不写第二份清洗逻辑。详见 [配置与数据](config-and-data.md)。
- **新增右键菜单项**要同步四处：`context_menus/registry.py` 的动作、`menu_templates/modern-default-v1.json`
  的节点、`tests/test_menu_layout.py`、`tests/test_desktop_pet_features.py` 的期望标签。
  详见 [设置与右键菜单](settings-and-menu.md)。
- **新增一种落盘数据**（数据目录里一个新文件或新目录，或者往别处写一个新文件）要在 `pet/data_stores.py` 的 `STORES`
  里登记一项，并回答「硬盘没了它从哪回来」；不是我们的数据（别家程序的文件、随包资源）就加进 `NOT_STORES` 写明是什么。
  `tests/test_data_stores.py` 扫源码里的文件名字面量，漏了就红。详见 [配置与数据](config-and-data.md) 的「存储表」。
- **设置页控件必须包在 `SettingRow` 里**。域聚合用 `findChildren(SettingRow)` 收集再搬进共享卡片，
  页面自己布局里的普通控件（包括按钮）搬不过去，会直接消失。行的键在 `objectName`（`settingRow_<key>`）。

## Qt 生命周期

- **跨线程只发 queued 信号**，接收者是 GUI 线程的 `QObject`。后台线程里不碰任何 `QWidget` / `QMediaPlayer`；
  跨线程 `QTimer.singleShot(0, app, callable)` 是 PySide6 的已知危险用法，不要用。
- **`destroyed` 的清理回调用不带接收者的 lambda**。对象在 C++ 侧被删时，它自己 bound-method 形式的
  `destroyed` 槽不会被调用。
- **`PetWindow.closeEvent()` 是窗口这个 owner 的统一关闭入口**，幂等（`_close_event_done`）。顺序：
  先处理外置气泡，再停联动、屏幕监视、输入、素材库、定时器和当前 reader。
- **`PetSpeechBubble` 没有 Qt 父对象**，是独立的 Tool 窗口，由创建它的窗口负责断开信号、`dismiss()` / `close()`，
  并在 GUI 线程用 `shiboken6.delete()` 同步销毁。留给 `DeferredDelete` 队列的话，会在不相干的时刻被冲刷出来。
- **右键菜单**生产路径用真实的 `QMenu.exec()`；测试替换 `_exec_context_menu()` 这个 Python 层 seam，
  不去 monkeypatch PySide 的 C++ 方法。
- 无界面（offscreen）测试发现不了线程和时序类回归。动了线程或生命周期的改动要在真机上跑一遍。

## 后台可选服务的写法

工作简报、Slack 关注、工作笔记、个人助理、知识库同步、记忆蒸馏、配置备份都是同一个模子：

- GUI 线程里一个 `QTimer` 定期 `check()`，**每次重新读配置**。所以设置保存后最迟一个周期生效，不需要「设置改了」的通知。
- 真要干活时起 daemon 线程，结果经信号排队回 GUI 线程落盘。
- 一个代数计数器（`_generation`）只在 `stop()` 时加一，晚到的结果作废；「忙」按任务各自记。一个服务里多种任务共用
  「每次启动就加一」的计数器，两个任务一交叠，先起的结果会被当成过期丢掉、忙标记永远不清。
- 阻塞函数、线程、时钟、「人在不在」都可注入，测试里换成同步的假函数。
- 启动后的第一次检查是错开的（知识库 8 秒、简报 20 秒、个人助理 25 秒、笔记 30 秒、蒸馏 40 秒、配置备份 60 秒、
  Slack 关注 90 秒）。新加的服务别挤在同一秒。
- 接线失败不阻断启动：`AppShell._start_*` 一律兜住异常、记日志后继续。旧的 `PetWindow` 形态不接这些服务。
- overlay 拓扑下 `AppShell` 里只遍历 `instances[].win` 的代码是空转（`win` 恒为 `None`），要交给 `OverlayShell`。

## Windows 上几条通用的坑

- **从不激活的置顶窗口被盖住后不会自己回来。** 灵动岛、通知卡片都靠周期性重申置顶。新做任何不抢焦点的置顶窗口都要带上，
  并把自家窗口排除在「被盖住」之外，否则两扇窗会轮流把对方压下去。
- **`SHQueryUserNotificationState` 的 2（忙）不能当全屏用**：最大化的 Electron 窗口、本进程自己的 overlay 合成窗都会让它报 2。
  只认 3（D3D 全屏）和 4（演示模式）。它也不反映「勿扰」。
- **样式表的 `font-family` 只写一个覆盖中文的字体族。** 多族列表或覆盖不了中文的族，会让 Qt 为了回退枚举整个字体库，
  常驻内存多几十到一百多 MB。首次画 emoji 同理（加载彩色字体栈约 +33 MB），小图标自己画线条。
- **不要改进程共享的 `ctypes.windll.user32` 的 `argtypes` / `restype`**，别处按 int 用它。需要按指针收窗口句柄时另起一份
  `ctypes.WinDLL("user32")`。
- **半透明的层叠窗口不要逐帧 `setGeometry` 做动画**：DWM 会先拿旧位图在新位置合成一帧。窗口一次到位，用遮罩揭示。
- **没有选择器的样式表会继承给子控件上建的 `QMenu`**。透明容器里弹的菜单要自己套样式。
- **菜单图标的线程规则**：后台线程只解码成 `QImage`，`QPixmap` 和 `QAction` 的更新回 GUI 线程；不要对正在显示的可滚动菜单
  连续 `setIcon()`。

## 会话结束冻结（Windows 关机 / 注销）

**问题**：Windows 关机时先发 `WM_QUERYENDSESSION`，随后拆登录会话。这之后再 `CreateProcess` 出来的进程
DLL 初始化失败，系统弹「应用程序无法正常启动 (0xc0000142)」并卡住关机。肥鱼的动画链随时可能起一个
ffmpeg 取帧进程，撞上的概率接近 100%。

**规则**：收到会话结束通知后，**不再派生任何 ffmpeg 进程**，已有的 reader 停掉。闸门是单向的：
关机被取消后进程也保持冻结，不恢复动画。

| 部件 | 位置 | 要点 |
|---|---|---|
| 闸门 | `pet/webm_clip.py`：`session_ending()` / `set_session_ending()` | 四条派生路径全部先查它：播放 reader、首帧预解码、元数据探测、ffmpeg 可执行文件探测。`start()` 返回 `False`，复用「启动被拒」的既有降级 |
| 预热 | `pet/library.py`：`stop_all_clips()`、`warm_predicted()` | 关机时只 `stop()`，不 join、不登记孤儿 |
| 探测 | `pet/session_watcher.py` | 应用级原生事件过滤器抓 `WM_QUERYENDSESSION` / `WM_ENDSESSION`，Qt 的 `commitDataRequest` / `aboutToQuit` 兜底。只读 `MSG` 的 `message` 字段，命中才解引用。恒返回 `(False, 0)`：只观测，不拦关机。同一个过滤器还处理锁屏 / 解锁和挂起 / 恢复 |
| 编排 | `AppShell._on_session_end()` | 幂等：置闸门 → 逐窗 `match_shutdown()` → 记日志 |
| 窗口 | `match_shutdown()`（`pet/window_optional_services.py`） | **先**停活动**再**置 `_closing`，顺序不能反（置位后停活动是空操作） |

- 关机时**不做**会话保存、写盘、解锁：既不必要，又拖长清理窗口。
- **新增任何 ffmpeg 派生点必须放在闸门里。** `tests/test_session_end_ffmpeg_guard.py` 按源码清单检查，
  漏了直接红。
- 闸门只管 ffmpeg。别处派生的进程（联动、启动器）理论上有同样的问题，出现同类报告时按同一个闸门收编。
- 真机验收：起肥鱼后运行 `python scripts/verify_session_end_shutdown.py`（投递与系统关机同号的消息，
  断言日志里出现停止记录、之后没有新的 ffmpeg 进程），再真的注销一次。
