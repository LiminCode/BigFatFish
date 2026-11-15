# 与上游的关系

> 本项目 fork 自 [MerZlin/dsh-pet-indesktop](https://github.com/MerZlin/dsh-pet-indesktop) 的 `main@ee699c7`（2026-10-06）。
> 这份文档讲：上游的旧文档去哪找、为什么只从源码运行、上游的改动怎么拿、帧序列这类从上游搬来的机制要注意什么。
> 对应的决定见 [ADR 0001](adr/0001-run-from-source-only.md) 和 [ADR 0002](adr/0002-cherry-pick-from-upstream.md)。

## 上游的文档

fork 时带来的上游文档（发版稿、打包与 CI 记录、在线更新协议、插件化路线、DSH 调研、主动识屏设计稿、交接快照、
上游自己的 PR 报告）在本项目里已经没有对应的东西，2026-11-02 移出了本仓库。要查某个机制在 fork 之前的来历：

- 上游固定版本：`https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/docs/<文件名>`
  （目录：[docs @ ee699c7](https://github.com/MerZlin/dsh-pet-indesktop/tree/ee699c7/docs)）。
- 本仓库的 git 历史：`git show ee699c7:docs/<文件名>`。
- 上游 README 原文（安装、使用教程、动画素材、v4.x 变更记录）：
  [README.md @ ee699c7](https://github.com/MerZlin/dsh-pet-indesktop/blob/ee699c7/README.md)。

代码注释里指向上游文档的链接都是这种固定版本的地址，不要改成本地路径。

## 只从源码运行

本项目只在本机从源码跑（`run.bat` / `python -m pet`），不出安装包、不发版。2026-10-11 删掉了构建与发布的基础设施：
三个平台的构建脚本、安装包定义、PyInstaller 入口、构建 / 发布工作流、产物瘦身与自检脚本及其测试、打包指南、在线更新。

**有意留下的**，判据是「删它要不要改 `pet/` 下的运行代码」，要改的都留着：

- 运行期给打包版准备的分支：`sys.frozen` 判断、`build_variant` 变体目录（`config._app_dir_name`）、
  `_MEI` 临时目录清理（`pet/runtime_cleanup.py`）。散在近十个模块里，源码运行时走不到。变体目录逻辑还被改名迁移用着。
- 「无聊天变体」的延迟导入约束：`modern_settings_dialog.py` 顶层不许 `import pet.chat`，`tests/test_architecture.py` 守着。
- `pet/uninstall_cleanup.py`（`python -m pet --uninstall-cleanup`）：移除注入到 Claude Code 的钩子，源码用户同样需要。
- `.github/workflows/pr-test.yml`：是测试门禁，不是打包。

**想恢复打包时要知道**：

- 文件从 git 历史取回（删除打包那次提交的父提交）。它们在被删前刚按新名字改过，那次改名没有经过实际构建验证；
  打包版的数据目录迁移也只有单元测试。
- 上游后来给帧序列加了打包期的硬门，本仓库没搬。
- 上游还在维护这些构建脚本，同步上游时它们会以「我方删除、对方修改」冲突，每次保持删除。

## 上游同步的做法

**不 merge，只按功能挑拣。** 上游把十来个模块改成了目录包，我们这边删了打包和更新器、改了程序名、做了界面语言和
Metro 设置页，试算整体合并有 130 个文件冲突。

怎么挑：

- 用户点名要的功能，加上能干净 `cherry-pick` 的修复；一步一个提交。
- 每一步先把上游的测试搬过来、确认在我们的代码上是红的，再动实现。
- 不能干净挑的，取上游最终版重新落地；同一个提交里混着不要的部分时只搬一半。

**有意不搬的**（再同步时不用重新评估，除非前提变了）：

| 上游的东西 | 不搬的原因 |
|---|---|
| 截图提问 | 随包 30 MB 的 OCR 加打包链；我们有 Claude 识屏 |
| 素材包市场、720p 几何、`library.py` 的 pack 部分 | 我们用自有素材 |
| 每屏一窗的多屏方案 | 我们自己做了 `pet/overlay_viewport.py` |
| TTS 后端注册表、每日一签、天气、DSH 修复、Android | 用不上 |
| 全局记忆 | 我们走个人知识库和[会话记忆蒸馏](memory-distill.md) |
| 聊天分页、深度思考 / 联网搜索开关 | Claude 通道自带 effort |
| 「回收内存」菜单 | 它清的是别的进程的工作集，不减肥鱼自己的内存 |

**搬过来时改了落点的**：

- **时间感知**。上游把「当前时间」写进 system。我们的 Claude 通道对 system 和消息前缀开着提示缓存
  （`pet/chat/anthropic_provider.py`），system 每分钟变一次会让整段历史每轮重写缓存。所以改成：发给模型的
  **用户消息**前加 `[日期 周X 时:分]` 标记（`chat/prompt.py` 的 `stamp_message` / `stamp_text`），system 末尾只放一句说明，
  距上条消息 ≥ 10 分钟才多一句间隔（`time_context`）。不变量：连续对话里 system 逐字不变；标记只在发给模型时附加，
  会话文件不改；助手消息不加标记。
- **设置窗提速**。根因值得记住：构造期对**没有父对象**的 `SettingRow` 调 `setVisible(True)` 会当场开出一个顶层窗口
  （先闪一个无标题小窗，构造 5.4 秒 → 0.86 秒）。新增设置行一律传 `parent`；
  `tests/test_modern_settings_rows_topwindow.py` 守着。

## 帧序列档位

- **档位串是采纳条件的一部分**：`frameseq_provision.ENCODER_DESC`。改它，全部旧世代失效，回退到 WebM 播放，
  后台按新档重新供给。也就是说**改档即全量重出**。
- 现在的档位是无损：`lossless=True` 加 `exact=True`。`exact` 不能去掉，libwebp 默认会改写 `alpha == 0` 像素的 RGB。
  `method=2` 是甜点：`method=6` 只再省约 2% 体积，编码慢 7 倍。链尾的 `floor_faint_alpha` 把 `a == 1` 的底板清成全透明
  （白色桌面上整只鱼外面那块浅灰矩形的来源）。
- **运行时迁移与命令行的分工**：运行时每次启动最多迁 1 个 clip（`MIGRATION_CLIPS_PER_ROUND`），只适合零星补转。
  改档后的全量重出用 `tools/convert_frameseq.py`，约 100 个 clip 要一个多小时。
- **全量重出必须在肥鱼停着时跑。** 肥鱼的后台供给会把不认识的 `.tmp` 半成品目录当残留清掉，结果目录
  「个数自洽、编号不从 1 开始」，再跑一遍还会按「同档已完整」跳过。症状是连点鱼几秒没反应，日志里成串
  `frameseq 预取超时 … thread_alive=True`。`frame_ends_present`（首尾两帧都在）卡在采纳闸门和发布前。
- 无损的代价只在磁盘（帧序列目录约 442 MB → 1408 MB）。解码后的帧是 RGBA 位图，运行时内存不涨。
- 预取线程是进程级共享的 3 条（`frameseq_clip.PREFETCH_THREADS`），退出时先全部 `quit` 再逐个 `wait`。

## 聊天窗的生命周期（从上游搬来，仍然生效）

- **关闭即销毁。** 两套聊天窗（`chat/widgets.py`、`chat/legacy_widgets.py`）的收尾统一挂在 `QDialog.done()`，
  `closeEvent` 只转发。Esc 走 `reject() → done()` 不经过 `closeEvent`，只写后者会留下指向已销毁窗口的监听器。
- **`WA_DeleteOnClose` 必须保持 False。** 销毁时机由 `chat/lifecycle.release_window_when_idle` 决定：`QThread` 运行中
  被销毁会崩进程，所以有在飞的 worker 时等它的 `finished` 再 `deleteLater`；连上信号后要再查一次（worker 可能恰好在
  判定与连接之间退出）；销毁前先 `service.detach()`。
- 应用层持有窗口的槽位按 `shiboken6.isValid` 判断能不能复用（`app._chat_window_usable`）。
- AI 回复按 Markdown 渲染，用户气泡永远是纯文本，复制按钮复制原文。
- 岛上的对话退出时不整份覆盖保存会话：完整聊天窗里已落盘的新消息不能被旧快照盖掉。

## 素材与许可

素材生成链（`tools/asset_pipeline/`）与提示词（`prompts/`）取自上游，相对上游的改动与许可见各自目录的 README 和
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)（脚本 MIT；提示词等素材禁止商用、须署名）。
配图池和 `raw-material/` 里有从网络收集的图片，出处与授权没有逐张核实，仅作个人非商业使用。仓库是公开的，
已推送的历史抹不掉，再往里加图之前要想清楚。
