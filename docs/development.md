# 开发指南

> 怎么跑、怎么测、怎么提交、怎么合并。工程纪律的权威版本是 [`AGENTS.md`](../AGENTS.md)，这里是它的操作细则。

## 运行

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install edge-tts      # 可选：语音报时要出声才需要
run.bat                                  # 或 .venv\Scripts\python.exe -m pet
```

- 只从源码运行，没有安装包和发版（见 [ADR 0001](adr/0001-run-from-source-only.md)）。
- 数据目录是 `%APPDATA%\big-fat-fish\`：`config.json`、日志 `pet-<pid>.log`、各功能的缓存与状态文件。
  运行中的进程不会热加载手改的 `config.json`，要么重启，要么经设置窗口保存。
- Windows 控制台默认 GBK，`Get-Content` 读 UTF-8 源码会显示乱码（文件没坏），加 `-Encoding UTF8`。
- `PET_RENDER_TOPOLOGY=overlay` 切到 overlay 拓扑（见 `AGENTS.md`）。

## 测试

```powershell
$env:QT_QPA_PLATFORM = "offscreen"                    # 无界面环境必须
$env:APPDATA = "$env:TEMP\bff-test-appdata"           # 别让测试碰真实配置
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\test_xxx.py
.venv\Scripts\python.exe -m ruff check pet tests
```

- **跑多大范围**按 `AGENTS.md` 的风险门：局部的界面或单个控件的行为，跑新测试加受影响的测试族就够，
  并在 PR 描述里写明为什么没跑全量；动了共享模型、配置迁移、生命周期、线程、平台分支的要跑全量
  （`python -m pytest -q`，约 10 分钟）。
- ruff 只开了 F 级规则，格式问题不会让 CI 变红。脚本化的批量改动之后必须重跑 ruff。
- **时序测试**：涉及真实线程、Qt 事件循环、动画的断言一律「轮询目标状态 + 宽预算」，
  不用固定 sleep 猜时序，不赌目录枚举顺序，不拿 `monotonic` 的绝对值做算术。
  先断言用户看得见的结果，内部句柄的收尾只作补充。CI 的慢 runner 比本机慢好几倍。
- **不要往 `tests/conftest.py` 加新的 autouse 夹具。** 多加一个就会改变全量套件里对象的回收时机，
  把潜伏的原生崩溃引出来；需要全局打桩时并进已有的夹具。
- **不要在测试里全局冲刷事件**（`sendPostedEvents(None, DeferredDelete)`、对共享 `QApplication` 调
  `processEvents()` 来清理）。它会把别的测试留下的删除任务引爆在当前测试里。自己创建的对象定向销毁。
- 测试不能真的启动外部程序（`wsl.exe`、`claude`、`gh`、浏览器）；这些边界在 `conftest.py` 里已经被换掉，
  新增的外部调用照此打桩。
- **只跑受影响的测试时，把扫全仓库的守卫带上**：`tests/test_architecture.py`、`tests/test_config_schema.py`、
  `tests/test_pr_report_discipline.py`、`tests/test_settings_english.py`、
  `tests/test_desktop_pet_features.py::test_product_copy_has_no_external_brand_reference`。新增目录名、文案、配置键、
  设置行最容易撞上它们，而且失败落在别的测试族里。改共享配置的默认值要跑全量：有测试靠旧默认值才不碰真机。
- **测试不读写真机状态**：Claude Code 的运行清单、hooks 检查、`wsl.exe` 在 `conftest.py` 里默认关掉，要测的用例自己打开并指到
  临时目录。默认值指向真实目录的设置（笔记仓库、知识库副本）在测试里必须显式指到临时路径。
- **给灵动岛加对外方法**后，`tests/test_single_process_shared.py` 里手写的假岛要补同名空方法；菜单测试的宿主替身对任何属性
  都回一个返回 `None` 的函数，新的菜单建造器要把回调的返回值按空清单处理。
- **断言样式令牌要明暗都认**：全量里前面的用例可能把调色板留成深色，只认浅色的断言单跑绿、全量红。
- **同批并行的 PR 各自开新测试文件**：都往同一个文件末尾追加，合并时 git 会把两段交错拼坏。
- **无界面平台没有中文字体**，截图里文字是方块，只能核布局和配色。看字用 `QT_QPA_PLATFORM=windows`；要给人看的卡片截图用
  `QWidget.grab()` 只渲染控件本身，数据用虚构的。没显示过的设置页不排版，先切过去再抓。
- **用真模型验证的功能只跑一两次**，对数据目录的副本跑（候选库复制一份、WSL 里把 `HOME` 换成沙箱、git 用临时裸仓库当远端）。
  PR 里只记结构与数字（成败、秒、轮数、条数），不记内容。
- 分不清是环境问题还是自己引入的：`git worktree add <临时目录> <改动前的提交>`，在同一台机器上跑同一条用例。
- CI（`.github/workflows/pr-test.yml`）把 webm 生命周期族、低优预热族、帧序列族隔离出主套件单独跑。
  同一族连修两轮不绿就隔离，不在 PR 门禁里赌时序。
- 全量套件随机原生崩溃的排查见 [排障手册](troubleshooting.md)。

## 提交与 PR

1. 从 `main` 起分支，小步提交。多个会话可能同时在用主检出：在自己的 worktree 里改，只提交自己改的文件。
2. 修行为先在公开接缝处写失败的测试，再改产品代码。
3. PR 描述按 [`.github/PULL_REQUEST_TEMPLATE.md`](../.github/PULL_REQUEST_TEMPLATE.md) 写，三份证据缺一不可：
   修改文件说明、性能分析（实测数字）、实机运行记录。纯文档 / 文案 / 依赖版本号的改动可只留第一份，写明豁免。
4. 仓库里的文档只按需留三种：

   | 情况 | 写在哪 |
   |---|---|
   | 用户看得见的变化 | [`CHANGELOG.md`](../CHANGELOG.md) 最上面加一行 |
   | 某个子系统的机制、不变量、排障结论变了 | 改 `docs/` 里对应的主题文档 |
   | 大改动（新功能域、架构边界、会被人想推翻的取舍、下线） | 新增一份 [ADR](adr/README.md) |

   不再为每个 PR 写报告文件。截图不入库，截到 `.scratch/screenshots/`。
5. 公开仓库：文档、测试、提交说明里不放真实人名、邮箱、工单号、公司内部名称和私人知识库的内容。推送前搜一遍。
6. 改设置项先过[设置变更门禁](settings-and-menu.md)；改配置键、菜单项的登记规则见[架构与红线](architecture.md)。

## 合并 PR

三条实际踩过的规律：

- **叠放的 PR 在父 PR 被 squash 之后一定冲突。** squash 在 `main` 上生成内容相同、提交不同的新提交，
  子分支里是原提交加后续修改，两边都改了同一批行。处理：先确认子分支的版本是父分支的加强而不是回退，
  再取子分支的版本，最后 `git diff <子分支>` 为空才算对。两侧互不相干时不能机械取一边，必须真合并。
  还要确认 PR 的**目标分支**是 `main`：合进一个已经没人用的旧分支，GitHub 照样显示 Merged，功能却不在 `main` 上。
- **红线和预算是组合性质。** 每个 PR 的 CI 只对自己的分支负责，两个各自合规的 PR 合到一起可能越线
  （行数预算、菜单顺序断言、品牌名守卫）。合并前把同期 PR 对受预算文件的增量加起来算一遍；
  会越线就先推一个校准提交，再合会越线的那个。
- **新测试先想最慢的平台。** 本机五次全绿不代表 CI 绿；固定 sleep 的时序测试在慢 runner 上是确定性地红。

合并后在主检出 `git pull --ff-only`，从 `main` 重启肥鱼确认真的生效。
