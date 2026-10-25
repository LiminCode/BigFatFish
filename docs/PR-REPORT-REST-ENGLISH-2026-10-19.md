# PR 报告：其余界面英文化——聊天窗、快速对话、拖文件解读、喂食 / 看屏幕气泡、待办、会话跳转等跟随「界面语言」

> **基线**：`90fc03c`（feat(settings): 内置表达风格不再是黑箱）
> **分支**：`feature/claude-session-fish`　**日期**：2026-10-19
> **范围**：33 个文件（实现 28、语言表 2、测试 1 新、脚本 1 新、文档 1）+ 本报告 + 2 张截图
> **关联**：[`PR-REPORT-SETTINGS-ENGLISH-2026-10-16.md`](PR-REPORT-SETTINGS-ENGLISH-2026-10-16.md)、
> [`PR-REPORT-MENU-ENGLISH-2026-10-16.md`](PR-REPORT-MENU-ENGLISH-2026-10-16.md)（同一套抽取 / 改写脚本，第三轮）

## 一、核心特性

用户 2026-10-19：「let's continue do the translation, check the rest, e.g. 个人助理, and 灵动岛, let's support both english and chinese」。

先按 AST 数了一遍整个 `pet/` 里运行时求值的中文字面量（排除 docstring、注释、日志、已经走 `t()` 的）：个人助理与灵动岛
的本体此前已走 `t()`（个人助理 2026-10-17 新建时即中英文；灵动岛只剩「（暂无最近消息）」一条）；真正还没翻的大头是
**聊天窗**（新版 + 旧版 + 旧版聊天内设置对话框 + 裁切对话框）、**快速对话气泡**、**拖文件解读**、**喂食 / 看屏幕气泡**、
**待办提醒**、**会话跳转 / VS Code 工作区的回话**、Claude / OpenAI 通道与知识库同步的**错误文案**，以及几处零散的对话框。

| # | 范围 | 说明 |
|---|---|---|
| 1 | 自动改写 | 27 个模块抽出 467 处运行时中文（去重 421 条），人工译成英文 327 条，改写成 `t("<模块>.<英文前几个词>")`（f-string 换成带命名参数的 `t(键, 名=表达式)`），同时写进中英两张表；校验占位符与 `%` 说明符一致。 |
| 2 | 有意不翻（译文标 `null`，共 94 条） | 给模型的提示词（识屏、拖文件解读的指令、知识库的工具说明与系统注记、主动识屏的活动分类）；内置台词与角色台词（听歌时的八句、动画名）；旧拓扑 `app.py` 的兜底托盘菜单（overlay 下不用）；关机步骤的日志标签；余额功能（2026-10-13 已下线）；会存进配置的彩蛋标题。 |
| 3 | 模块级字面量（脚本不碰，手工） | 聊天窗「需要授权」通知的默认正文改成留空时取 `t()`；快速对话的「…（全文见聊天窗）」改成用时 `t()`；会话来源「终端 / VS Code 插件 / SDK」改成键、显示时翻（会话小鱼详情卡与灵动岛历史都走它）。 |
| 4 | 不该翻的别翻 | 聊天窗判断「是不是认证失败」靠在错误文案里找关键词，脚本把「认证失败 / 未授权 / 授权」三个关键词也换成了 `t()`——英文界面下会去找英文词而漏掉中文错误；改回字面量并加注释。 |
| 5 | 截断 | 英文「Follow the fish」在聊天窗左下角的固定宽度按钮里被截成「Follow…e fish」，改成「Follow fish」。 |

**不变量**：中文界面逐字不变（33 个相关测试文件 1076 例不改一行即过，除下述两处按新设计改的旧断言）；配置里存的值不变；
给模型的提示词不变。

## 二、修改文件说明

| 文件 | 增删 | 改动 |
|---|---|---|
| `pet/chat/widgets.py` | +90 / −89 | 新版聊天窗 86 条：侧栏（新建 / 会话 / 批量管理 / 置顶 / 删除 / 跟随肥鱼）、输入区占位与提示、附件校验与文件过滤器、状态行（就绪 / 思考中 / 生成中）、系统通知（对话完成 / 需要授权 / 生成失败）、删除确认。认证关键词改回字面量；授权通知默认正文留空时取 `t()`。 |
| `pet/chat/legacy_widgets.py` | +48 / −47 | 旧版聊天窗 45 条（同上一套）。 |
| `pet/chat/settings_dialog.py` | +37 / −36 | 旧版聊天内设置对话框 40 条；局部变量 `t` 改名 `theme`（会遮住翻译函数）。 |
| `pet/chat/crop_dialog.py` | +11 / −10 | 裁切对话框 6 条；循环变量 `t` 改名 `frac`。 |
| `pet/chat/utils.py` | +3 / −2 | 「新会话」标题。 |
| `pet/chat/providers.py`、`anthropic_provider.py` | +13 / −12、+19 / −18 | 两条通道的错误文案 26 条（认证失败、模型不存在、连接器出错、空回复、轮数上限、连接成功…）。 |
| `pet/chat/knowledge_base.py` | +10 / −10 | 知识库同步的 11 条错误（压缩包过大、找不到仓库、Token 被拒…）；给模型的工具说明与注记不翻。 |
| `pet/vision.py` | +11 / −10 | 识屏的 8 条错误 / 限流文案；提示词不翻。 |
| `pet/quick_chat.py` | +11 / −10 | 快速对话气泡 8 条 + 截断后缀。 |
| `pet/file_interpret.py` | +19 / −18 | 拖文件解读 20 条（询问、进度、完成、失败、附件标题）。 |
| `pet/overlay_shell.py`、`pet/file_eater.py` | +11 / −14、+7 / −9 | 看屏幕 6 条、喂食 6 条（两处同一套）。 |
| `pet/app.py` | +17 / −18 | 隐藏 / 恢复提示、开机自启失败、设置窗口已打开、切换角色失败等 17 条；兜底托盘与余额不翻。 |
| `pet/proactive.py` | +2 / −1 | 「让我看看……」；活动分类（进提示词）不翻。 |
| `pet/dynamic_island.py` | +1 / −1 | 「（暂无最近消息）」。 |
| `pet/todo_reminder.py` | +7 / −6 | 下次提醒摘要、提醒气泡 6 条。 |
| `pet/claude_session_jump.py`、`pet/vscode_workspaces.py` | +13 / −12、+6 / −5 | 跳转 / 工作区的回话 19 条。 |
| `pet/claude_session_info.py` | +6 / −3 | `ENTRY_TEXT` 存键，`entry_text` 显示时 `t()`。 |
| `pet/fun_image_popup.py`、`click_talk_dialog.py`、`music_lyric_controller.py`、`slack_watch_ui.py`、`agent_cost.py`、`personal_service.py` | 各 +1～+6 | 零散对话框 / 气泡文案。 |
| `pet/locale/zh.json`、`en.json` | 各 +334 / −1 | 333 个键。 |
| `scripts/capture_chat_window.py`（新） | +44 | 新版聊天窗按语言渲染成 PNG。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_rest_english.py`（新） | +101 | 英文下新版 / 旧版聊天窗与快速对话气泡的全部可见文案（text / placeholder / tooltip / title）不含中文，关键条目英文；中文聊天窗不变；会话来源跟随语言、不认识的入口原样；这一轮全部新键两张表齐全、英文里不含中文。 |

### 未改动

- 给模型的提示词（识屏、解读、知识库注记、个人 / 工作简报）：模型按用户语言回复，提示词语言不影响界面。
- 内置台词预设 `pet/persona_presets/*.json` 与听歌八句：中文内容；要英文台词得另做英文预设（见「后续」）。
- 旧拓扑 `pet/window.py`（PetWindow，只修崩溃）与 `app.py` 的兜底托盘。

## 三、实现要点

- 复用前两轮的抽取 / 改写脚本，只换文件清单与键名前缀（这次前缀本身带命名空间：`chat.window` / `chat.classic` /
  `file_interpret.ui` …）。
- 两类不能机械改的：**用作判断的字符串**（认证关键词）要改回去；**模块级字面量**（默认参数、常量）要改成用时取。
  `ruff` 的 F402 / F823 抓出两处局部变量叫 `t` 的——改写前它们恰好没和翻译函数同名冲突。

## 四、性能分析

| 指标 | 实测 / 说明 |
|---|---|
| 语言表 | zh 1576 键 / en 1584 键（本轮 +333）；进程内各读一次缓存 |
| 聊天窗建窗口 | 多 ~90 次字典查表；`tests/test_rest_english.py` 建三次窗口 + 一次气泡共 0.73 s（offscreen），与改前同量级 |
| 气泡 / 错误文案 | 每处一次查表，发生频率是用户动作级（拖文件、看屏幕、出错） |
| 运行时 | 无新系统调用 / 网络 / 线程；内存多 ~330 个短字符串 |

**结论**：① 稳态零开销；② 每次建聊天窗 / 冒气泡多几十次字典查找，测不出；③ 无新 I/O；④ 内存可忽略。

## 五、实机运行记录

- **盘点**（`count.py`，AST 计数）：改前整个 `pet/` 运行时中文最多的是内容表（节日语录 199、持久化模板说明 153、动画名 140、
  台词兜底 124、报时语录 120），界面类最多的是 `chat/widgets.py` 102、`app.py` 47、`overlay_shell.py` 45、`chat/legacy_widgets.py` 56、
  `chat/settings_dialog.py` 37。个人助理 10 条全是提示词 / 工具错误，灵动岛 4 条（3 条是旧占位键）。
- **截图**（`QT_QPA_PLATFORM=windows` 真实字体，`scripts/capture_chat_window.py`）：
  `docs/screenshots/chat-english-2026-10-19/chat-window-{zh,en}.png`。英文版看过：标题、侧栏、「Start a new conversation」、
  「Sessions / Today」、占位「Say something to the fish… Enter to send, Shift+Enter for a new line」、「Quick mode · Ready」；
  第一版左下角「Follow the fish」被截成「Follow…e fish」，改成「Follow fish」。
- **红灯**：`tests/test_rest_english.py` 在改动前——聊天窗可见文案含 85 条中文、会话来源是「终端」——全部失败；改后 5 例绿。
- 肥鱼已重启（结束不含 `--settings` 的主进程，`run.bat` 拉起，`acquired pid=28216`，日志无 Traceback）；用户配置里界面语言是
  English，看屏幕 / 喂食 / 解读的气泡与聊天窗即为英文。本机没有能点真实气泡的自动化工具，以上是渲染与单元层的证据。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `ruff check pet tests scripts` | All checks passed（改写后先报 F402 / F823 两处 `t` 遮蔽，已改名） |
| 聚焦 | `pytest -q tests/test_rest_english.py` | 5 通过 |
| 相关族 | 名字含 chat / quick_chat / file_interpret / file_eater / vision / proactive / todo / session_jump / vscode / slack / agent_cost / island / click_talk / personal_ui / i18n / settings_english / menu_english / anthropic / knowledge_base / about_user / desktop_pet_features 的 31 个文件 | 743 通过，2 失败 = 既有基线（路径超 260、多显示器负原点） |
| 全量 | `python -m pytest -q -p no:cacheprovider`（offscreen，临时 APPDATA，从 Git Bash 启动） | `6 failed, 5454 passed, 11 skipped in 509.68s (0:08:29)`：4 个本机既有基线 + 1 个 Git Bash 启动才有的既有编码失败 + 1 个本次引入：`tests/test_second_batch.py::test_quick_chat_bubble_truncates_long_ai_reply` 读的是被改成键的常量 `_REPLY_PREVIEW_SUFFIX`，改成经 `t()` 取并断言中文原文后通过（该文件 11 通过 1 跳过）。 |

## 七、已知限制与后续

- **内置台词预设是中文内容**：英文界面下 Agent 联动气泡仍说中文（默认 / 鲸鱼娘两套 JSON）。要英文台词，可以加 `legacy.en.json` /
  `whale_maid.en.json` 按界面语言选，或用「改成我的台词」后让 AI 改写成英文导入——需要用户定。
- 旧拓扑 PetWindow 与 `app.py` 兜底托盘未翻。
- 节日语录、报时语录、动画名是内容，不在界面语言范围内。

## 八、风险与回滚

- `git revert` 即可；无配置迁移、无行为改动。
- 风险点：被当作判断依据的中文字符串——认证关键词已改回；其余 COMPARE / DICTKEY 场景脚本本来就跳过。
