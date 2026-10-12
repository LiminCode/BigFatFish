# PR 报告：删除打包与发布部分

> **基线**：`b992184`（refactor!: 程序改名 dsh-pet-standalone → big-fat-fish）
> **分支**：`feature/claude-session-fish`　**日期**：`2026-10-11`
> **范围**：36 个文件（删除 25、修改 10、新增本报告 1）
> **关联**：[`PR-REPORT-BIG-FAT-FISH-RENAME-2026-10-11.md`](PR-REPORT-BIG-FAT-FISH-RENAME-2026-10-11.md)
> （同日早些时候刚给这些打包文件改过名，那一轮登记了「打包与 CI 未验证」）

## 一、核心特性

本项目只从源码在本机运行（`run.bat` / `python -m pet`），不出安装包也不发版。用户要求
删掉打包发布部分以减轻维护负担。

删除的是**构建与发布的基础设施**：三个平台的构建脚本、安装包定义、打包入口、四条
GitHub Actions 构建 / 发布工作流、产物校验脚本及其测试、两份打包指南、更新清单。共 25 个
文件、3,502 行。

**没有删的**（判断依据写在 §七，都是可以后续再议的）：

- 运行期代码里给打包版准备的分支（`sys.frozen` 判断、`build_variant` 变体目录、
  PyInstaller `_MEI` 临时目录清理）。它们散在十来个模块的启动、自启、资源定位路径里，
  源码运行时走不到；逐个拆除是对运行代码动手术，收益只是少几行。
- 「无聊天变体」留下的约束：设置窗口对 `pet.chat` 的延迟导入及其架构测试。
- `pet/uninstall_cleanup.py`（`python -m pet --uninstall-cleanup`）：原本给卸载程序调用，
  但它做的事——移除注入到 Claude Code 的钩子——源码用户同样需要。
- `.github/workflows/pr-test.yml`：它是测试门禁，不是打包。
- 带日期的历史文档（各版本发布说明、构建产物记录、在线更新说明）。

**不变量**：运行行为不变。没有改 `pet/` 下任何文件。

## 二、修改文件说明

增删取自 `git diff b992184 --numstat`。

### 删除（25 个文件）

| 文件 | 行数 | 是什么 |
|---|---|---|
| `.github/workflows/build-windows.yml`、`build-macos.yml`、`build-linux.yml` | 125 / 127 / 138 | 三个平台的构建与发布工作流 |
| `.github/workflows/republish-assets.yml` | 80 | 把构建产物重新挂到 Release |
| `packaging/dsh-pet.iss` | 81 | Inno Setup 安装包定义 |
| `packaging/pet_entry.py`、`pet_entry_no_chat.py` | 34 / 16 | PyInstaller 入口（含 / 不含聊天） |
| `scripts/build_onedir.ps1`、`build_macos.sh`、`build_linux.sh` | 514 / 108 / 102 | 三个平台的本地构建脚本 |
| `scripts/build_pyside6_fcitx_plugin.sh` | 82 | Linux 包里输入法插件的构建 |
| `scripts/slim_bundle.py`、`fix_bridge_bundle.py` | 294 / 138 | 产物瘦身、DSH 桥接插件打包修正 |
| `scripts/check_bundle_encoding.py`、`verify_bundle_qt.py`、`verify_bundle_tts.py` | 314 / 61 / 257 | 产物自检（编码、Qt DLL 链、TTS） |
| `scripts/cleanup_mei_cache.py` | 98 | 清理 PyInstaller onefile 留下的 `_MEI*` 目录 |
| `tools/ext_ws_probe.py` | 189 | 对打包后的 exe 做进程外内存采样 |
| `update.json` | 15 | 在线更新清单（指向上游的发布页；更新功能此前已移除，代码里没有读它的地方） |
| `tests/test_bundle_slim.py`、`test_bundle_encoding_check.py`、`test_fix_bridge_bundle.py`、`test_verify_bundle_tts.py` | 239 / 158 / 81 / 114 | 上面那些脚本的测试 |
| `docs/ONEDIR_PACKAGING.md`、`docs/STABLE_BUILDS.md` | 105 / 32 | 打包流水线指南、稳定版构建冻结记录 |

### 修改

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `tests/test_desktop_pet_features.py` | +0 / −12 | 删 `test_windows_build_regenerates_the_icon_before_pyinstaller`（断言的是构建脚本的内容） |
| `tests/test_requested_regressions.py` | +0 / −26 | 删 `test_build_scripts_bundle_menu_templates_and_chat_styles`（同上） |
| `tests/test_chat_subsystem.py` | +0 / −26 | 删 `test_no_chat_packaging_uses_isolated_entrypoint`（读打包入口与构建脚本） |
| `tests/test_settings_process_isolation.py` | +0 / −11 | 删 `test_packaging_entries_route_settings_before_importing_app`（读打包入口） |
| `tests/test_voice_chime_service.py` | +3 / −14 | `test_build_scripts_and_requirements_declare_edge_tts` 收窄为 `test_requirements_declare_edge_tts`：去掉对三个构建脚本的断言，保留「`requirements.txt` 必须声明 edge-tts」 |
| `AGENTS.md` | +6 / −3 | 两条指向已删文档的「改打包 / 改发布前必读」换成一条：打包发布已移除、只从源码运行、运行期的打包分支是故意留下的 |
| `docs/INDEX.md` | +2 / −3 | 去掉两份已删文档的登记；「疑似过时」清单里 `STABLE_BUILDS.md` 一项改为「已删除」；登记本报告 |
| `docs/DEV-HANDOVER.md` | +2 / −2 | 去掉两处对 `ONEDIR_PACKAGING.md` 的引用 |
| `README.md` | +2 / −1 | 「移除的功能」表加一行；「与上游的关系」里不再说打包产物名 |
| `.github/workflows/pr-test.yml` | +3 / −3 | 两处注释里提到的 `build-*.yml` 已不存在，改写 |

### 未改动

`README.md` 下半部分保留的上游文档原文仍有下载、安装包、构建的章节，并链接到已删除的
`docs/ONEDIR_PACKAGING.md`（两处死链）。那部分是原样保留的上游文档，没有逐段修改；在
「移除的功能」表里写明了它们在本项目不适用。`docs/ONLINE-UPDATE.md` 同样有两处死链，
它本身是已移除功能的历史说明。`requirements.txt` 里有四处注释提到 PyInstaller 的收集
行为，依赖本身没有变，注释未动。

## 三、实现要点

**怎么确定删哪些测试。** 先删文件，再跑引用过它们的测试文件，红的 5 条就是依赖：
4 条的断言对象整个没了，删除；1 条有一半断言的是 `requirements.txt`，留下那一半。

**为什么不动运行期分支。** 判据是「删它需不需要改 `pet/` 下的运行代码」。需要的都留下
了：那些分支在源码运行时不执行，留着的成本是阅读时多看几行；拆它们则要改启动、自启、
资源定位这些路径，每一处都得补测试、跑全量、实机验证，与「减轻负担」的目的相反。
其中 `build_variant` 相关的变体目录逻辑在上一份改名报告里刚刚被迁移代码用到。

## 四、性能分析

本改动不触及任何运行代码（`pet/` 下 0 个文件变更），桌宠的运行路径、系统调用、网络、
磁盘、线程、内存都没有变化，没有可测的运行期指标。能测的是仓库与测试侧：

| 指标 | 改动前 | 改动后 |
|---|---|---|
| 受版本控制的文件数（`git ls-files \| wc -l`） | 890 | 866（含本报告） |
| 全量测试条数（通过 + 失败 + 跳过） | 4,987 | 4,952（少 35 条） |
| 全量测试耗时（本机，单次） | 384.65 s | 462.37 s（这一次运行期间同时在重启桌宠和写报告，耗时不可与左栏直接比较） |

逐条回答：① 稳态开销无变化；② 没有新增路径；③ 没有新的系统调用 / 网络 / 磁盘 / 线程；
④ 内存无变化。

## 五、实机运行记录

**从源码重启桌宠**（`run.bat`，真实配置目录），确认启动不依赖任何被删的文件：

```text
2026-10-11 22:30:08 acquired pid=51956 lock=C:\Users\limin\AppData\Roaming\big-fat-fish\overlay-instance.lock
2026-10-11 22:30:08,322 INFO big-fat-fish 启动 (slot: 0, instance: )
2026-10-11 22:30:19,373 INFO 台词语音预缓存跳过：本地 TTS 服务不可用（<urlopen error timed out>）
进程：".venv\Scripts\BigFish.exe" -m pet    （pid 51956）
```

启动后 20 秒内日志里没有 `Traceback`、`ModuleNotFoundError` 或「找不到文件」。唯一含
「error」字样的是上面那行 TTS 预缓存跳过，它是本机没有运行本地 TTS 服务时的既有提示，
与本改动无关。

**依赖关系的现场确认**：删除前对每个待删文件做了 `git grep`，`pet/` 下的引用只有两处
注释（`pet/config.py` 里提到 `build_onedir.ps1`、`pet/vision.py` 里提到 `pet_entry`），
没有代码导入或读取它们。

**没有验证的部分**：GitHub 上的 `pr-test.yml` 没有实际跑过（只改了注释）。macOS / Linux
未运行。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests scripts tools`、`git diff --check` | 通过 |
| 聚焦 | 引用过被删文件的 10 个测试文件 | 删文件后 5 条红（即 §二 处理的 5 条）+ 1 条既有基线；处理后只剩基线那 1 条 |
| 受影响时序族满载 3 遍 | — | 不适用：没有新增或修改带时序的测试 |
| 全量 | `python -m pytest -q -p no:cacheprovider`（`QT_QPA_PLATFORM=offscreen`，`APPDATA` 指向临时目录） | `4 failed, 4937 passed, 11 skipped in 462.37s`。4 个失败是这台机器上一直存在的环境性失败（路径超 260、两条子进程输出按 cp1252 解码、多显示器负原点），与本改动无关。本报告是在这次运行开始之后才写的，`tests/test_pr_report_discipline.py` 另外单独跑过 |

## 七、已知限制与后续

- **运行期的打包分支还在**（`sys.frozen`、`build_variant`、`_MEI` 清理、无聊天变体的延迟
  导入约束）。它们现在是不可达代码，可以另开一轮按模块拆除。
- **上游文档原文里的死链**（README 两处、`ONLINE-UPDATE.md` 两处）没有修。
- **与上游的差异继续扩大**：上游还在维护这些构建脚本，以后合并上游时这些文件会以
  「我方删除、对方修改」的形式冲突，需要逐次选择保持删除。
- 以后要恢复打包，从 `b992184` 取回这 25 个文件即可；注意它们在那个提交里刚被改过名
  （`big-fat-fish-<变体>`），且那次改名没有经过实际构建验证。

## 八、风险与回滚

- **影响面**：仓库内容与测试集；运行行为不变。
- **配置 / 落盘**：无。
- **回滚**：`git revert` 本提交即恢复全部文件，无残留状态。
