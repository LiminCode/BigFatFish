# PR 报告：灵动岛图标改成「点一下选自己的图片」（2026-10-20）

> **基线**：`2d20dff2`（docs(report): 置顶报告补第二轮全量结果）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-20
> **范围**：6 个文件 + 4 张截图（实现 2、文案 2、测试 1、文档 2）
> **关联**：岛这边的 `img:<路径>` 图标早就支持（`pet/dynamic_island.py` 的 `_ICON_IMG_PREFIX`），本改动只换设置页的入口。

## 一、核心特性

用户要求：设置页「桌面组件」里的「图标」不要再是下拉框，点一下就直接打开选文件，让用户放自己的图片。

以前那一行是下拉框：鱼本体头像 + 十个 emoji。岛其实认 `img:<路径>`，但设置页没有入口，用户只能手改配置文件。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 点方块直接选图 | 图标方块就是按钮：点一下直接弹出系统选文件对话框，不经过菜单；从「图片」文件夹开始，只列图片（png / jpg / jpeg / webp / bmp / gif / tif）。 |
| 2 | 存一份自己的副本 | 选中的图读进来，最长边缩到 128 像素、存成 PNG，放进肥鱼配置目录的 `island-icons/`，文件名带内容哈希。原文件以后移走 / 删掉都不影响。 |
| 3 | 回到默认 | 「恢复默认」（第一轮叫「用鱼本体头像」，第二轮改名）回到 `auto`；已经是默认时置灰。 |
| 4 | 清理旧副本 | 保存时删掉 `island-icons/` 里不再用的副本，只留当前那张；回到默认时全部删掉。 |
| 5 | 失败不改 | 取消 = 不改；选的不是能读的图片 = 不改，行下面说一句原因。 |
| 6 | 旧 emoji 设置不丢 | 以前在下拉框里选过 emoji 的，不动它就原样保存，岛照旧画；方块旁写「表情图标（旧设置）」。设置页不画 emoji 本身（首次画 emoji 会加载彩色字体栈，约 +33 MB）。 |
| 7 | 中英文 | 全部文案走 `t()`。 |

**红线 / 不变量**：配置格式不变（`dynamic_island.icon` 仍是 `auto` / `img:<路径>` / 文字）；岛的绘制、缓存、换图刷新逻辑不变；「显示图标」关掉时这一行照旧隐藏。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/settings_island_icon.py` | 新增 | `import_icon(source, data_dir)`：`QImage` 读图，超过 128 就等比缩小，PNG 编码后按内容 SHA-1 前 12 位命名写进 `island-icons/`（同内容不重复写）；读不了返回 None。`prune_icons(data_dir, keep)`：删掉除当前值以外的 `icon-*.png`。`IslandIconPicker`：方块（`TiltButton`，点 = `choose()` 直接调 `QFileDialog.getOpenFileName`）+ 状态文字 +「用鱼本体头像」+ 出错时的一行说明。`island_icon_row` / `save_island_icon` 给设置对话框用，写法同 `settings_tray.py`。 |
| `pet/modern_settings_dialog.py` | +5 / −20 | 删掉 `island_icon_select` 下拉框和十个 emoji 选项；这一行改由 `settings_island_icon.island_icon_row` 建；保存时 `"icon"` 取 `save_island_icon(self)`（顺便清理旧副本）。行的 key 仍是 `dynamic_island_icon_value`，「显示图标」开关的联动不用改。 |
| `pet/locale/zh.json` | +9 / −12 | 新增 `settings.island_icon.*` 9 条；删掉下拉框专用的 12 条（头像推荐、十个 emoji 名字、旧提示），代码里已无引用。 |
| `pet/locale/en.json` | +9 / −12 | 同上。 |

### 测试

| 文件 | 覆盖 |
|---|---|
| `tests/test_settings_island_icon.py`（新增，9 个用例） | 这一行是方块不是下拉框、默认状态；点方块直接调一次系统对话框（标题、图片过滤、起始目录是存在的文件夹）；副本在配置目录、PNG、最长边 128、保持宽高比、保存后配置是 `img:<副本>`；原文件删掉后岛照样读得到图（像素颜色对得上）；取消不改、不建目录；非图片不改并给原因；重置回 `auto`、保存时清副本；旧 emoji 原样保存；「显示图标」关掉时行隐藏；英文文案。 |

### 文档

| 文件 | 改动 |
|---|---|
| `docs/PR-REPORT-ISLAND-ICON-PICKER-2026-10-20.md` | 本报告（新增）。 |
| `docs/INDEX.md` | +1 行：PR 报告存档登记。 |
| `docs/screenshots/island-icon-2026-10-20/` | 4 张：中 / 英 × 默认 / 选了图之后（只截设置行控件本身，示例图是脚本画的橙色小鱼）。 |

### 未改动

- `pet/dynamic_island.py`：`img:` 的读取、缓存（读失败也缓存，不每帧碰盘）、设置保存后清缓存，原本就有。
- `pet/config.py`：`icon` 的归一化（`img:` 限长 260）不用改；副本路径远短于这个。

## 三、实现要点

- **为什么复制而不是记原路径**：用户说的是「上传自己的」。记原路径的话，图片在下载文件夹里被清掉、或 OneDrive 只留在线文件时，岛就静默回退成空图。复制进配置目录后，图标归肥鱼自己管。
- **为什么缩到 128**：岛把图标 `QPixmap` 原样缓存在内存里，再按 22 逻辑像素 × DPR 缩放画出来。用户选一张 4000×3000 的照片，旧做法会让岛常驻 4000×3000×4 字节 ≈ 46 MB 的位图；缩到 128 后是 128×128×4 = 64 KB。200% 缩放下图标也只要 44 像素，128 绰绰有余。
- **为什么用内容哈希命名**：换一张图就换一个文件名，配置值一定变，岛那边按配置值清缓存的逻辑天然生效；同一张图重复选不会重复写。
- **什么时候复制、什么时候清理**：选图那一刻就复制（预览显示的正是将要存的那张）；保存时才清理旧的（用户选了又取消整个设置窗口，留下的副本会在下一次保存时清掉）。
- **emoji**：下拉框时代的十个 emoji 选项去掉了；老配置里的 emoji 值不动就原样写回，用户点「用鱼本体头像」或选图才会换掉。

## 四、性能分析

**方法**：`PYTHONIOENCODING=utf-8 python <scratchpad>/probe_icon.py <repo> <out> en|zh`（Windows 真平台，不是 offscreen；临时配置目录，不碰真实桌宠配置）。
环境：Windows 11 Pro 26300，Python 3.13.15，PySide6（仓库 `.venv`）。每种语言各跑 3 次，下表取最后一轮。

| 指标 | 实测 | 归属 |
|---|---|---|
| 选图后导入 + 刷新预览（900×900 PNG 源图） | 22.8 ms（英）/ 18.6 ms（中） | 新增；只在用户选图时跑一次 |
| 副本大小 | 3027 字节，128×128 | 新增磁盘占用；只留当前一张 |
| 岛常驻的图标位图（计算：宽×高×4 字节） | 选 4000×3000 照片时，旧做法 ≈ 46 MB，现在 64 KB | 既有路径的内存上限变小 |
| 系统对话框从点击到出现 | < 1.3 s（探针看到窗口后再等 0.6 s 才关，总 1.3～1.8 s） | 系统对话框自身，不是本改动的开销 |

**结论**：① 稳态开销：没有。岛的绘制路径没改；设置页建这一行少了一个 11 项的下拉框，多了一个按钮和两个标签。② 新增路径：只在用户点方块、选好图时跑一次 ≈ 20 ms；保存时 `prune_icons` 列一次 `island-icons/` 目录。③ 新的磁盘访问：选图时读源图、写一个几 KB 的 PNG；保存时可能删旧副本。没有网络、没有新线程。④ 内存：岛缓存的自定义图标从「原图多大就多大」变成最多 64 KB。

## 五、实机运行记录

在本机 Windows 真平台（非 offscreen、非 mock 对话框）用临时配置目录打开真实的设置窗口：

```
native dialog seen: True | title: Choose an island icon | closed after 1.3s
value after cancel: auto
start dir: C:/Users/<me>/OneDrive/Pictures
import + preview: 22.8 ms
stored: cfg\big-fat-fish\island-icons\icon-6aa7415a59ff.png 3027 bytes (128, 128)
saved icon value is img: True

native dialog seen: True | title: 选择灵动岛图标 | closed after 1.3s
```

- **点方块真的弹出了系统对话框**：探针在点击后枚举顶层窗口，找到了类名 `#32770`（Windows 通用文件对话框）、标题是本地化的「Choose an island icon / 选择灵动岛图标」的可见窗口，再发 `WM_CLOSE`（等于用户按取消）。取消后值仍是 `auto`。
- **起始目录**：`QStandardPaths` 给的「图片」文件夹，这台机器上在 OneDrive 下。
- **选图之后**：探针把系统对话框换成返回一张脚本画的示例图，走同一个导入函数：副本落在配置目录 `island-icons/`，128×128，保存后配置值是 `img:<副本>`。
- **截图**：`docs/screenshots/island-icon-2026-10-20/icon-row-{default,custom}-{en,zh}.png`。第一次截图时英文「Use fish avatar」按钮右边被截了一点，加了按文字定最小宽度后重截正常。
- **没能自动做的**：在系统对话框里真的点选一个文件——那是系统窗口，我这边没有能驱动它的工具；探针只证明它弹出来了、标题和起始目录对。请用户在设置里点一次图标方块、选一张自己的图、保存，看岛上换没换。
- **桌宠不用重启**：设置窗口是每次打开时新起的进程，下次打开就是新代码；岛的读图逻辑没改。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests` | All checks passed |
| 红→绿 | 先写 `tests/test_settings_island_icon.py`，改实现前收集即失败（模块不存在）；改后 9 过 | ✔ |
| 相关 | `test_settings_island_icon / test_i18n / test_settings_english / test_architecture / test_desktop_pet_features / test_config_schema / test_settings_metro / test_settings_save_without_exit / test_island_topmost / test_island_english / test_settings_and_resources / test_settings_process_isolation` | 233 passed（去掉 1 个路径超 260 的基线用例） |
| 受影响时序族 | 不涉及线程 / 事件循环时序 | 豁免 |
| 全量 | 隔离 worktree，`-X faulthandler`，临时 `APPDATA` | 见下 |

全量结果：`4 failed, 5520 passed, 11 skipped in 633.98s (0:10:33)`（隔离 worktree，HEAD `2d20dff2` + 本改动）。4 个失败是本机既有的环境性基线（路径超 260 / 子进程 cp1252 解码 ×2 / 多显示器负原点），与前两轮相同，没有原生崩溃。这一轮全量跑的副本还没有「Use fish avatar」按钮按文字定宽那一行（截图之后才加的纯外观改动）；加上之后重跑了 `tests/test_settings_island_icon.py`，9 过。

## 第二轮（同日）：「试了不好使」→ 选好立刻生效、按钮改名、加「打开文件夹」

用户在真设置窗口里试了，说不好使；另要一个按钮打开图片存放的地方。

### 现场证据（用户本机，真实配置目录）

| 时间 | 证据 | 说明 |
|---|---|---|
| 15:40:07 | 设置进程启动（新代码） | 进程表里 `--settings` 那个的启动时间 |
| 15:41:03 | `island-icons/` 目录创建 | 用户选了一张图，导入成功（读不了的图不会建目录） |
| 15:41:35 | 肥鱼日志「灵动岛拖拽落点」 | 用户拖了一下岛；肥鱼 `_save_position` 写一次配置 |
| 15:41:44 | `config.json` 与 `island-icons/` 同一秒被改，目录变空，`dynamic_island.icon` = `auto` | 设置窗口那次保存时控件里的值已经是 `auto`，所以把刚导入的副本当旧副本清掉了 |

复现：照真实设置进程的构造参数（`standalone=True, include_ai=True`）+ 真的「保存」按钮、中间插一次「肥鱼写配置」，
选图后保存都正确（`img:` 写上、副本保留）——保存逻辑本身没错。能解释「15:41:44 存成 `auto`」的只有：保存前控件被改回了默认，
也就是按了那个叫「用鱼本体头像」的按钮。这个名字很容易被读成「把这张图用作鱼的头像」——选完图正想「用上」，按下去恰好是撤销。
再加上第一轮的设计要点「选完还要点保存」，岛没有立刻变，用户自然觉得没反应。我没有能证明用户点了哪个按钮的日志，以上是证据最吻合的解释。

### 改法

| 文件 | 增删 | 改动 |
|---|---|---|
| `pet/settings_island_icon.py` | +93 / −14 | `write_icon_now(config, value)`：选好图 / 恢复默认的那一刻，把**磁盘上**配置里的 `dynamic_island.icon` 这一项改掉（读文件 → 只改这一项 → 临时文件 + `atomic_replace_with_retry`，与 `Config.save` 同格式），同时更新设置窗口手里的那份；没有配置文件时退回 `config.save()`。只改一项是因为设置开着时肥鱼也会写配置（拖岛记位置），整份写回会把它冲掉。写上之后才 `prune_icons`。「用鱼本体头像」改名「恢复默认」；加「打开文件夹」（先建好目录再 `QDesktopServices.openUrl`）；结果一行 `message_label`：「已换上…」「已恢复默认…」或读不了的原因、写不进配置的原因。 |
| `pet/locale/zh.json`、`en.json` | 各 +8 / −3 | 新文案 5 条，改 3 条（提示、默认状态、按钮名）。 |
| `tests/test_settings_island_icon.py` | +60 / −17 | 选图后**不点保存**，重新从磁盘读配置就是 `img:`；恢复默认同样立刻落盘、副本清掉；换第二张图时第一张的副本随手清掉；肥鱼在中间写进去的 `x / y` 不被冲掉；「打开文件夹」打开的正是 `island-icons/` 且目录先建好；按钮新名字、中英文。 |

红→绿：改测试后 7 红 4 绿（4 个是取消 / emoji / 开关隐藏 / 删原图——行为没变的那些），改实现后 11 过。

### 实机运行记录（第二轮）

- **正在跑的肥鱼、真实配置**（脚本用真的 `IslandIconPicker` 指向用户的 `config.json`，只把系统对话框换成返回一张脚本画的橙色测试图）：

  ```
  config: config.json icon before: auto
  picked: img: | message: Done. The island will show it in a moment.
  on disk now: img:
  island shows test image: True after 0.6s (orange px before=9, now=731)
  reset message: Back to the default fish avatar. | on disk: auto
  island back to default: True
  copies left: []
  ```

  截的是岛左端那一小块屏幕（`docs/screenshots/island-icon-2026-10-20/live-island-test-image.png`）：选图后 0.6 秒岛上就是测试图，
  没有点保存；恢复默认后换回、副本清空，用户配置回到原来的 `auto`。
- **「打开文件夹」**：点真按钮后，用 `Shell.Application` 枚举资源管理器窗口，找到 1 个停在 `island-icons` 的窗口（随后关掉）。
- **系统对话框**：同第一轮探针，点方块弹出 `#32770`，标题中英文都对。
- **设置行截图**重拍（中 / 英 × 默认 / 选了图之后），新按钮「恢复默认」「打开文件夹」都没被截字。
- **用户那边要做的**：当时开着的设置窗口（15:40 启动）已经是第一轮的代码；请关掉重开一次，再点方块选图——选完岛上马上换。

### 性能（第二轮）

| 指标 | 实测 | 说明 |
|---|---|---|
| 选图到岛上换图 | 0.6 s（上面那次实机） | 主要是肥鱼配置监视器的 300 ms 去抖 + 重画；新增的写盘本身见下行 |
| 导入 + 预览 + 写配置 | 24.2 ms / 22.7 ms（英 / 中） | 比第一轮多一次读写 `config.json`（约 25 KB） |

稳态没有变化；新增的是每次选图 / 恢复默认各一次配置文件读写，没有新线程、没有网络。

### 全量（第二轮）

隔离 worktree（HEAD `04e4c45d` + 本轮代码，截图不参与），`-X faulthandler`，临时 `APPDATA`：`4 failed, 5524 passed, 11 skipped in 566.92s (0:09:26)`。4 个失败与前几轮相同，都是本机既有的环境性基线，没有原生崩溃。

## 七、已知限制与后续

- 选 GIF 只取第一帧（存成 PNG），岛上的图标不会动。
- 不提供裁剪：非方形的图等比缩进方块，两边留空。
- 下拉框里的十个 emoji 不再能选；用户真想要 emoji，可以选一张 emoji 图片。

## 八、风险与回滚

- 没有新配置键，格式不变。旧版本读到 `img:<副本路径>` 照样能画（岛一直支持）。
- 回滚：`git revert`；`island-icons/` 里留下的副本无害，可以手动删。
