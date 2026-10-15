# PR 报告：界面里不再叫「桌宠」，改叫「肥鱼」；设置页左下角的版本号去掉（2026-10-14）

> **基线**：`b167144`（chore(menu): DeepSeek 的入口全部下线，`feature/claude-session-fish`）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-14
> **范围**：约 190 个文件（`pet/` 与 `tests/` 里凡是含「桌宠」的 .py / .json 都改了一处或多处；版本号 3 个文件；文档 2）
> **关联**：[`PR-REPORT-SETTINGS-METRO-2026-10-14.md`](PR-REPORT-SETTINGS-METRO-2026-10-14.md)（同一天的设置页改版）

## 一、核心特性

用户：「不要用桌宠，用桌面助手，或者你想一个更好的名字」；「设置页左下角的版本号可以去掉，我们现在不发版」。

**名字定为「肥鱼」**，没有用「桌面助手」。理由：

- 这个项目就叫 BigFatFish，菜单里早就是「生小肥鱼」「退出子肥鱼」「主肥鱼」的说法；把主体叫「肥鱼」，
  「隐藏肥鱼」「肥鱼设置」「肥鱼控制」「随肥鱼启动」读起来自洽，不用再解释「桌面助手」是谁。
- 两个字比四个字短：胶囊卡片的按钮「显示肥鱼 / 隐藏肥鱼」、侧栏域名「肥鱼」、右键分组「肥鱼控制」都不用重排。
- 英文表（`pet/locale/en.json`）早就写的是 "Show the fish / Hide the fish"，中英一致了。

要换成「桌面助手」也只是再跑一遍同一个替换脚本（`桌宠 → 桌面助手`）。

**改法**：`pet/` 与 `tests/`（含 `scripts/`）里所有 `.py` / `.json` / `.sh` 文件中的「桌宠」整词替换成「肥鱼」——界面文字、
提示、日志、注释、docstring、测试断言一起改，口径统一；**不碰** `docs/`、`README.md`、`.agents/`（历史文档与对外说明保持原样，
README 以后单独整理）。186 个文件、833 处。配置键、标识符都是 ASCII，不受影响；没有产生「肥肥鱼」这类叠词。

**版本号**：设置页侧栏左下角「版本 vX.Y.Z」那一行去掉（控件、样式规则、import 一起删）。`pet/__init__.py` 的 `__version__`
本身还在（别处还有人读）。

**红线 / 不变量**：
- 只是文字：没有任何行 id、配置键、信号名、文件名变化；设置页的域仍是九个，只是第二个域叫「肥鱼」。
- 英文模式的文字不变（英文表本来没有「桌宠」）。
- 会话小鱼、灵动岛、右键菜单、托盘、气泡文案都跟着改，没有一处还写「桌宠」（用例守着：`pet/` 与 `tests/` 里 `grep 桌宠` 为 0）。

## 二、修改文件说明

### 实现

| 文件 | 改动 |
|---|---|
| `pet/**/*.py`、`pet/locale/zh.json`、`pet/persona_presets/*.json`、`pet/menu_templates/*.json` 等（凡含「桌宠」者） | 「桌宠」→「肥鱼」整词替换。改动最多的：`app.py`（60 处）、`modern_settings_dialog.py`（46）、`window.py`（39）、`agent_link.py`（33）、`island_collision.py` / `overlay_shell.py`（各 20）。 |
| `pet/modern_settings_dialog.py` | 另：删侧栏版本号 `QLabel`（5 行）与 `from . import __version__`。 |
| `pet/settings_theme_qss.py` | 删 `QLabel#settingsVersion` 规则。 |

### 测试

| 文件 | 改动 |
|---|---|
| `tests/**/*.py`（凡含「桌宠」者） | 断言里的「桌宠设置」「桌宠控制」「隐藏桌宠」「桌宠」域名等同步改为「肥鱼…」。 |
| `tests/test_update_entry_removed.py` | 「仍显示版本号」用例改为「没有版本号」（属性不存在、`settingsVersion` 标签找不到）。 |
| `tests/test_architecture.py` | 设置页行数预算 2296 → 2291。 |

### 未改动

- `docs/`、`README.md`、`.agents/`：历史与对外文档里的「桌宠」原样（README 要改就是一次通篇校订，单独做）。
- `pet/__init__.py::__version__`：还在。

## 三、实现要点

- 整词替换而不是只改界面字符串：注释、日志、docstring 一起改，避免代码里「桌宠」「肥鱼」混用；替换前后 `grep` 计数守着。
- 没有引入「名字常量」：137 处界面字符串分散在 40 多个模块，抽常量的收益不如一次替换脚本——下次要改名再跑一遍脚本即可。

## 四、性能分析

纯文字改动与删一个标签，没有新增运行路径；侧栏少一个 `QLabel`。

| 指标 | 实测 | 归属 |
|---|---|---|
| 设置页侧栏控件 | 少 1 个 `QLabel` | 既有路径 |
| 其余 | 字符串长度变化在个位数字节 | — |

**结论**：① 稳态开销无变化；② 没有新增路径；③ 没有新的系统调用 / 线程；④ 内存可忽略。

## 五、实机运行记录

- **替换脚本输出**：`files: 186, replacements: 833`；替换后 `grep -rn 桌宠 pet tests scripts` 为 0；`grep 肥肥鱼|小肥鱼鱼` 为 0。
- **测试**：下线守卫 / 菜单编排 / 桌宠功能（现叫肥鱼功能）/ 设置资源 / 互动标签 / 岛对话 / 前台抢焦 / 岛碰撞 / 既往回归 /
  岛接线 / 菜单等价 / i18n / 岛英文 / hook / 架构守卫 `403 passed, 3 skipped`，失败 1 个是这台机器固定的
  `image_directory_picker` 路径超 260。`ruff check pet tests scripts` 通过。
- **全量**：见本节末尾。
- **真实桌面**：用真实 `APPDATA` 重启了肥鱼（`pet-overlay-gate.log`：`2026-10-15 00:13:35 acquired pid=14120`，新进程日志无
  Traceback）；在本进程里建真实设置对话框核对：
  ```
  title: 肥鱼设置 | sidebar: ['常规', '肥鱼', '互动', '菜单', '桌面组件', 'AI 与对话', '自动化与联动', '语音', '文件识别']
  version footer label: None | any 桌宠 in labels: False
  ```
  截图里「常规」页的说明文字全部是「肥鱼」（「登录系统后自动启动肥鱼」「始终将肥鱼保持在其他窗口上方」……），
  侧栏左下角没有版本号，「应用启动」只剩「开机自启」一行。截图含本机路径，没有入库。

**没有验证的部分**：README 与文档里的「桌宠」没改（故意）；英文模式不受影响、没有重截图。

**全量结果**（隔离 worktree `bffv3` = 基线 `b167144` + 本补丁，`python -m pytest -q -p no:cacheprovider`，
`QT_QPA_PLATFORM=offscreen`、`APPDATA` 指到临时目录）：

```
4 failed, 5274 passed, 11 skipped, 248 warnings in 585.30s (0:09:45)
```

4 个失败全是这台机器上固定的环境性失败（`image_directory_picker` 路径超 260、`festival_id_guard` 子进程按 cp1252 打印中文、
`real_second_process`、`capture_window_rect` 多显示器负原点），不含本改动的代码上同样失败。
