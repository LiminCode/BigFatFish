# PR 报告：右键菜单「YouTube Music」；网易云 / QQ 音乐整块下线

> **基线**：`bec5900`（docs(report): 修正桂冠报告第三轮里被转义吃掉的桥文件路径）
> **分支**：`feature/claude-session-fish`　**日期**：`2026-10-15`
> **范围**：22 个文件（实现 10 含删除 1、测试 9 含删除 2 与新增 1、文档 3 含本报告）
> **关联**：[`PR-REPORT-VSCODE-WORKSPACES-MENU-2026-10-13.md`](PR-REPORT-VSCODE-WORKSPACES-MENU-2026-10-13.md)（「音乐」子菜单下线）、
> [`SETTINGS-CHANGE-GATES.md`](SETTINGS-CHANGE-GATES.md)

## 一、核心特性

用户：「我不需要打开网易云或者 QQ 音乐放音乐，而是需要 YouTube 音乐」；随后定了范围：「不需要打开后自动
开始播放，打开地址是首页就好，网易云 / QQ 音乐可以删掉」。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 右键菜单「YouTube Music」 | 主菜单一项，紧跟「VS Code 工作区」；点了用默认浏览器打开 `https://music.youtube.com/`，不带播放参数，不自动开始播放。旧版菜单同样有 |
| 2 | 网易云 / QQ 音乐下线 | 去掉：找这两个程序的模块（`pet/music_players.py`）、启动时在几个盘符里找它们的后台扫描、设置页「网易云音乐程序 / QQ音乐程序 / 自动检测播放器」三行、配置键 `music_player_paths`、「打开并播放」的启动代码 |
| 3 | 歌词与唱歌照旧 | 歌词气泡、唱歌动画读的是系统媒体会话，Chrome 里的 YouTube Music 也在其中；只要打开「浏览器媒体会话参与歌词」。这一行的说明和「显示歌词」的说明改为以 YouTube Music 为例 |

「音乐」子菜单在 2026-10-13 已从右键菜单下线（用户当时的决定），网易云 / QQ 音乐的菜单入口早已不在；
这次删的是它们背后还在运行的部分，其中启动扫描每次启动都会做。所以新入口放成主菜单的单独一项，
没有恢复「音乐」子菜单。

**红线 / 不变量**

- 「音乐」子菜单仍然不存在（`test_menu_music_entries_removed.py` 全部保留，只把「默认模板里没有 `music`」
  这条放宽为「除了 `youtube_music` 没有 `music_`」）。
- 歌词功能的配置项（`music_lyric_enabled` 等）不变；旧配置里的这些值加载后原样还在
  （`test_the_player_path_setting_is_dropped_from_old_configs` 同时断言了这一点）。
- 歌词仍查 QQ 音乐 / lrclib / 网易云三个公开接口（`pet/music_lyric.py` 未动）：那是查词的来源，与用哪个
  播放器无关。
- 用户保存过的菜单编排不被打乱：新入口按模板位置补进去
  （`test_a_saved_menu_layout_picks_it_up_beside_the_vscode_entry`）。

## 二、修改文件说明

增删取自 `git diff --numstat bec5900`。

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/context_menus/shared.py` | +14 / −148 | 新增 `YOUTUBE_MUSIC_URL` 与 `add_youtube_music()`（`QDesktopServices.openUrl`，与宿主无关，新旧两套菜单、`PetWindow` 都能用）。删除 `_MusicLaunchBridge` / `_music_launch_bridge` / `_launch_player_and_play` / `_music_player_builder` / `add_music_open_netease` / `add_music_open_qqmusic`，以及随之不再用的 `os` / `sys` / `time` / `QProcess` 导入 |
| `pet/context_menus/registry.py` | +4 / −2 | 注册 `youtube_music`：标签「YouTube Music」、图标 `play`、无可用性条件 |
| `pet/context_menus/legacy.py` | +2 / −0 | 旧版菜单在「VS Code 工作区」后面加同一项 |
| `pet/menu_templates/modern-default-v1.json` | +1 / −0 | 默认模板在 `vscode_workspaces` 后面加 `youtube_music` |
| `pet/music_players.py` | 删除（−219） | 找网易云 / QQ 音乐程序：手填路径、盘符浅扫、进程内缓存、后台预热 |
| `pet/app.py` | +0 / −27 | 删除 `_warm_music_player_paths` / `_schedule_music_player_warm` 和素材加载完成后的那次调用——这是每次启动 2.5 秒后在后台扫盘的那段 |
| `pet/now_playing.py` | +0 / −53 | 删除 `player_process_running` / `_play_session_async` / `play_session_for`（只给「打开并播放」用）。读当前播放、暂停 / 切歌这些不变 |
| `pet/settings_music.py` | +9 / −171 | 只留「浏览器媒体会话参与歌词」那一行；说明里的例子从「网页版网易云」改为 YouTube Music |
| `pet/modern_settings_dialog.py` | +2 / −6 | 不再创建、装配、保存播放器路径三行；「显示歌词」的说明去掉网易云那句和已经不存在的「右键菜单 → 音乐 → 歌词对齐」，改为提示 YouTube Music 要开浏览器媒体会话 |
| `pet/config.py` | +0 / −24 | 去掉 `music_player_paths` 的默认值、两处白名单与清洗函数。加载只拷白名单里的键，所以旧配置里的这个键下次加载时自然丢掉，保存后从文件里消失 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_youtube_music.py`（新增） | +169 / −0 | 9 条：默认模板位置与标签；新旧两套菜单里点它只打开首页（`openUrl` 是唯一打桩的系统边界）；`PetWindow` 旧菜单；用户保存过的编排补进新项且不动用户顺序；播放器模块与启动函数已不存在；旧配置里的 `music_player_paths` 加载即丢、歌词配置照旧；设置页没有那三行、歌词设置还在；浏览器媒体会话那行以 YouTube Music 为例；默认模板仍没有「音乐」组 |
| `tests/test_music_player_cache.py` | 删除（−608） | 被测对象（播放器路径缓存、启动预热、启动并播放）整块下线 |
| `tests/test_music_player_settings.py` | 删除（−266） | 被测对象（设置页播放器路径三行）下线 |
| `tests/conftest.py` | +0 / −17 | 删掉「禁止测试里真扫盘找播放器」的 autouse 打桩——被打桩的函数没了。没有新增任何 autouse fixture |
| `tests/test_config_schema.py` | +0 / −66 | 白名单快照去掉 `music_player_paths`；删掉它的四条清洗用例 |
| `tests/test_menu_layout.py` | +6 / −3 | 默认模板与渲染顺序里加「YouTube Music」；设置页归属断言从播放器路径行换成 `music_lyric` |
| `tests/test_desktop_pet_features.py` | +1 / −0 | 旧菜单顺序里加「YouTube Music」 |
| `tests/test_menu_music_entries_removed.py` | +3 / −2 | 「歌词配置还在」不再要求 `music_player_paths`；模板里只允许 `youtube_music` 这一个带 music 的 id |
| `tests/test_runtime_dependencies.py` | +6 / −8 | `psutil` 仍须声明（会话小鱼核对进程、跳转认窗口用它），用例改名并改写理由；不再断言 `player_process_running` |

### 文档

| 文件 | 内容 |
|---|---|
| `README.md` | 「玩法与外观」加「YouTube Music」；「移除的功能」加网易云 / QQ 音乐一行 |
| 本报告、`docs/INDEX.md` | 登记 |

### 未改动

- `pet/music_lyric.py`：查词仍用 QQ 音乐 / lrclib / 网易云三个公开接口。
- `pet/music_lyric_controller.py`：有一句提示「用右键菜单「音乐 → 歌词对齐」校正」，指向 10-13 已下线的菜单，
  只在播放器不上报进度时弹出。Chrome 会上报进度（代码里的既有记录），YouTube Music 碰不到它，这次没动。
- `shared.py` 里其余 `add_music_*`（暂停 / 切歌 / 歌词对齐）自 10-13 起已不在任何菜单里，不属于网易云 / QQ 音乐，没删。

## 三、实现要点

**为什么是主菜单的单独一项，而不是恢复「音乐」子菜单。** 「音乐」子菜单是用户 10-13 决定拿掉的。这次只需要
一个「打开 YouTube Music」，一项就够；放在「VS Code 工作区」后面，同属「打开某个东西」。用户可以在 设置 → 菜单
里自己挪。

**为什么不自动播放。** 用户明确不要。顺带也避开了它的难点：只打开首页时 Chrome 还没有媒体会话，没有对象可以
发「播放」；要自动播放得靠带歌单参数的地址和 Chrome 的自动播放策略，结果不稳定。

**旧配置键怎么处理。** `Config` 加载时只拷白名单里的键，把 `music_player_paths` 移出白名单就是迁移：已有配置里的值
下次加载时丢掉，保存时不再写回。不需要单独的迁移代码。这个设置除了「打开网易云 / QQ 音乐」外没有别的用途，
留着只会是一个没有效果的设置（`SETTINGS-CHANGE-GATES.md`「旧 key、旧入口有明确去向」）。

**SETTINGS-CHANGE-GATES 各项**：契约（键删除、去向如上）、TDD（先红后绿，见 §六）适用；布局与可访问性、跨平台、
截图不适用——这次只从「音乐关联」组里删掉三行，没有新增控件；新菜单项沿用既有的菜单项构造，没有新的样式或平台分支。

## 四、性能分析

**方法**：

- 删掉的启动扫描：一次性脚本在改动前的代码上对两个播放器各调一次 `music_players.find_player`（先清缓存），
  重复 3 轮；本机两个播放器都没装，所以每次都会扫完所有盘符。
- 新菜单项：离屏 Qt 里连续构造 `add_youtube_music` 200 次为一轮，30 轮取中位。

环境：Windows 11 10.0.26300，Python 3.13.15；新菜单项那组测量时全量测试正在后台运行。

| 指标 | 实测 | 归属 |
|---|---|---|
| 启动后台扫描（网易云 + QQ 音乐，没装） | 3.39 s / 4.57 s / 3.94 s（3 轮） | **删除**：此前每次启动、素材加载完 2.5 秒后在后台线程里跑一次 |
| 构造「YouTube Music」菜单项 | 中位 50.7 µs / 次 | 新增：每次打开右键菜单 1 次 |
| 点击 | 一次 `QDesktopServices.openUrl` | 新增：用户点时 1 次 |

**结论**

1. **稳态开销**：没有新增常驻工作。每次启动少一段 3～5 秒的后台扫盘：对 C:/、D:/、Program Files、用户
   AppData 等根目录各做最多三层的浅扫，每个根最多 200 个目录。
2. **新增路径**：右键菜单每次多构造一个菜单项，约 51 µs；点击时交给系统打开网址。
3. **新的系统调用 / 网络 / 磁盘 / 线程**：新增的只有点击时的一次「打开网址」。少了启动时的扫盘线程和那段
   磁盘读。
4. **内存**：少了播放器路径缓存（两个条目）和一个模块；没有新增。

## 五、实机运行记录

**问题的现场**（只读探针）：本机两个播放器都没装，`music_players.find_player` 对两者都返回 `None`；默认浏览器
是 Chrome（`ChromeHTML`）；用户配置里 `music_lyric_enabled = False`、`music_browser_media_enabled = True`、
`music_player_paths = {}`。也就是说，此前每次启动都要白扫一遍盘去找两个不存在的程序。

**点击路径**：用真实的 Qt 平台（`windows`，不是 offscreen），用产品代码构造这个菜单项并触发：

```text
chrome windows before: 1 | any YouTube Music title: False
qt platform: windows
label: YouTube Music | url: https://music.youtube.com/
any Chrome window titled YouTube Music now: True
YouTube Music - Google Chrome
```

点击之后，默认浏览器 Chrome 打开了 YouTube Music 首页。

**用户自己的菜单编排**：用新代码解析用户真实的 `config.json`（只读），新项自动补到「VS Code 工作区」后面，
其余顺序不变：

```text
normalized ('default-action-added:youtube_music',)
['厉害了我的鲸', '|', '护驾', 'AI 对话', '看看屏幕', '|', '播放动画', '切换角色', '播放速率', '大小',
 'VS Code 工作区', 'YouTube Music', '|', …]
```

**没有验证的部分**

- **没有在运行中的肥鱼上右键点过这一项。** 本会话没有驱动桌面鼠标的手段；上面的点击是同一段产品代码在
  独立进程里触发的。
- **没有在 YouTube Music 里放歌，验证歌词与唱歌联动。** 放歌会在用户机器上出声；Chrome 的媒体会话能上报
  曲名与进度是代码里的既有记录，本次没有复测。
- 旧配置里的 `music_player_paths` 要等新代码下一次加载并保存配置后才会从文件里消失。

## 六、测试与验证

在独立的 git worktree 里做（同一工作区里还有别的会话在改代码、跑测试），用主仓库的 `.venv`。

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests`、`git diff --check` | 通过 |
| 红 → 绿 | `tests/test_youtube_music.py` 等 | 实现前 `8 failed, 91 passed, 3 errors`（errors 是打桩 `shared.QDesktopServices` 时它还不存在）；实现后全绿 |
| 聚焦 + 相关 | `test_youtube_music` `test_menu_music_entries_removed` `test_menu_layout` `test_config_schema` `test_runtime_dependencies` `test_sprite_menu_parity` `test_desktop_pet_features` `test_architecture` `test_now_playing_media_type` `test_now_playing_session` `test_music_lyric` | `1 failed, 364 passed`；失败的是本机一直有的 `test_image_directory_picker_…`（路径超 260），变基到 `bec5900` 前后结果相同 |
| 受影响时序族满载 3 遍 | — | 不适用：新用例没有线程或计时；删掉的用例里的时序（后台预热）随被测代码一起没了 |
| 全量 | `python -m pytest -q -p no:cacheprovider`（`QT_QPA_PLATFORM=offscreen`，`APPDATA` 指向临时目录，在独立 worktree、从 Git Bash 启动） | `5 failed, 5254 passed, 11 skipped in 472.90s`，在变基到 `bec5900` 之后的代码上运行。5 个失败是这台机器上一直存在的环境性失败（路径超 260、三条子进程输出编码、多显示器负原点），与本改动无关。这次运行之后只加了 README、本报告与索引登记 |

## 七、已知限制与后续

- 不自动播放（用户的决定）；在浏览器里听歌要显示歌词，需打开「浏览器媒体会话参与歌词」（用户本机已开）。
- 打开的是默认浏览器；默认浏览器不是 Chrome / Edge 时，歌词能不能取到取决于那个浏览器是否接入系统媒体会话。
- `music_lyric_controller.py` 里指向已下线菜单的那句提示，留待下次动歌词时一起改。

## 八、风险与回滚

- **影响面**：右键菜单多一项；设置页「音乐关联」少三行；启动少一次后台扫盘。歌词 / 唱歌链路没变。
- **配置 / 落盘**：删除配置键 `music_player_paths`（加载时丢弃）；没有新增配置键。
- **回滚**：`git revert`。回滚后 `music_player_paths` 回到默认的空值，已经从文件里丢掉的手填路径不会回来；
  本机此前就是空值。
