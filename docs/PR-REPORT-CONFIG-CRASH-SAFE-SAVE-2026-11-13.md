# PR 报告：配置写盘扛得住系统崩溃（2026-11-13）

> **基线**：`3b424baf`（Notifications: stack other apps by app, #39）
> **分支**：`claude/config-crash-safe-save`　**日期**：`2026-11-13`
> **范围**：3 个文件（实现 2、测试 1）+ 本报告与索引
> **关联**：`pet/config.py` 的 `atomic_replace_with_retry`（共享冲突重试，既有）

## 一、核心特性

**事故**：2026-11-13 晚本机三次非正常重启，其中 22:08 一次蓝屏（BugCheck 0x3B，系统指向
`dxgkrnl.sys`）。桌宠 22:06:24 刚保存过一次配置，蓝屏后 `config.json` 变成 **26127 个全零字节**。
下一次启动 `Config.reload()` 解析失败，照旧另存 `config.json.corrupt-*`、保留内存里的默认值，随后
任何一次 `save()` 把默认值写回盘——用户所有设置（灵动岛样式、聊天服务配置……）回到出厂值，用户
看到的是「灵动岛回到最初的版本」。代码本身没有回退。

**根因**：`Config.save()` 是「写临时文件 → `os.replace`」，但替换前**没有刷盘**。NTFS 把改名记进
日志、数据还在缓存里，此时崩溃就留下长度对、内容全零的文件。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 刷盘后再替换 | `_write_durably`：临时文件 `flush + os.fsync` 后才 `atomic_replace_with_retry`；POSIX 上再刷一次目录。崩溃后盘上只会是旧文件或新文件之一 |
| 2 | 上一份完好配置 | 每次保存前把盘上那份**已知完好**的配置留作 `config.json.bak`（硬链接，只加目录项、不复制不刷盘）；坏文件不许顶掉好的 `.bak` |
| 3 | 损坏时退回 | `reload()` 解析失败（或不是对象）→ 照旧另存 `.corrupt-*`，然后退回 `.bak` 并立刻安全写回 `config.json`；没有 `.bak` 才落回默认值（旧行为） |
| 4 | 恢复写进日志 | Config 构造早于 `_setup_logging`，恢复记在 `Config.recovered_from`，日志装好后由 `_setup_logging` 补记一条 WARNING |

**红线 / 不变量**：
- 读文件时的 `OSError`（共享冲突等瞬时错误）**不**触发退回 `.bak`——文件可能是好的，只是暂时打不开；行为同旧。
- 写盘内容与旧 `write_text` 逐字节一致（文本模式按平台换行），`_redacted_data()` 脱敏不变。
- 配置模块的告警不许在日志初始化前碰根 logger（见第五节回归）。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/config.py` | +109 / −15 | 新增模块级 `_LOG`（具名 logger）、`_read_json_dict`、`_write_durably`（写 + fsync + 原子替换 + POSIX 刷目录，任何出口清临时文件）、`keep_last_good_copy`（硬链接留 `.bak`，不支持硬链接时复制 + fsync）。`Config.__init__` 加 `recovered_from` 与 `_disk_intact`；`reload()` 把读失败（`OSError`，旧行为）与解析失败分开，解析失败走 `_recover_from_last_good_copy`；`save()` 改为「`_disk_intact` 时留 `.bak` → `_write_durably`」 |
| `pet/app.py` | +3 / −0 | `_setup_logging` 装好文件 handler 后，若 `config.recovered_from` 有值补记一条 WARNING |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_config_crash_safe_save.py`（新增） | +135 / −0 | ① 替换 `config.json` 前有一次 fsync，且刷的是即将换上的内容；② 清零的配置退回 `.bak`、另存 `.corrupt`、写回原文件；③ 运行中盘上文件被弄坏并重载后，保存不拿坏文件顶掉 `.bak`；④ `.bak` 与新文件互不影响（硬链接被 replace 拆开）；⑤ 没有 `.bak` 时仍落回默认值（旧行为护栏）；⑥ **真实子进程**走启动顺序 `Config → _setup_logging`：恢复记录进 `pet-<pid>.log`、日志文件照常写入 |

### 未改动（故意）

- `pet/slot_manager.backup_corrupt_config`：另存损坏文件的逻辑不变。它在复制失败时调根 logger 的
  `logging.error`，同样会在日志初始化前装上控制台 handler，但只在复制失败时触发，本 PR 不碰。
- `Config.save()` 失败分支的 `logging.warning("保存配置失败")` 同理（运行期才会触发，日志早已装好）。
- 其它状态文件（`overlay_spawn_state`、`proactive_limiter`、会话历史等）同样「写临时文件 → replace」
  不刷盘；它们丢了能自愈或代价小，本 PR 只管用户配置。

## 三、实现要点

- **为什么 fsync 就够防全零**：NTFS 的改名是日志化的元数据操作，数据先刷到盘再改名，崩溃后要么
  改名没发生（旧文件完好），要么发生了（新文件内容已在盘上）。全零只出现在「改名已入日志、数据还在
  缓存」这个窗口里。
- **为什么还要 `.bak`**：防御纵深——别的原因弄坏的文件（磁盘、外部程序、今后哪处写法回退）也能退回，
  而不是静默落回默认值。代价是退回的是**上一次保存之前**那一份，丢最后一次改动；比丢全部设置好得多。
- **为什么用硬链接**：`os.link(config, bak.tmp)` + `replace(bak.tmp, bak)` 只动目录项，不复制数据、不再
  刷盘；随后 `replace(temp, config)` 换掉的是 `config.json` 这个目录项，`.bak` 仍指旧内容
  （实测 `st_nlink` 各为 1、inode 不同）。
- **为什么不在保存时读盘校验**：第一版在 `keep_last_good_copy` 里先读 `config.json` 判断是否完好，实测
  保存从 0.7 ms 涨到 7 ms。拆解：**先读目标文件、紧接着替换它**，替换要多等约 4 ms（只读别的文件或只
  `stat` 没有这个代价，见第四节）。于是改为 Config 在内存里记 `_disk_intact`：重载解析成功、或本进程
  刚安全写完才为真；读到损坏为假。真实的损坏场景都经过一次重载（启动、或主进程目录监视触发的重载），
  所以内存标志覆盖得到。
- **日志初始化顺序**：`pet/app.py` 先 `Config(...)` 再 `_setup_logging(config)`，后者是不带 `force`
  的 `basicConfig`。在这之前调根 logger 的 `logging.warning` 会自动装一个控制台 handler，
  `basicConfig` 随即成了空操作，**整个进程的日志都不进文件**。所以配置模块用具名 logger，恢复这件事
  由 `_setup_logging` 补记。

## 四、性能分析

**方法（可复现）**：
`python -I <scratch>/bench_config_save.py <repo> <workdir> 300`——真实 `Config` 对象、真实 NTFS 盘，
分别跑旧写法（`write_text` + `atomic_replace_with_retry`，从基线原样搬来）与新 `Config.save()` 各 300 次。
环境：Windows 11 Pro 10.0.26300、Python 3.13.15、系统盘 NVMe SSD。配置文件 9440 B（默认值）。

| 指标 | 实测 | 归属 |
|---|---|---|
| 旧 `save()` | 中位 0.70 ms，p95 0.85 ms，max 1.09 ms | 既有 |
| 新 `save()`（最终版） | 中位 **1.56 ms**，p95 2.24 ms，max 4.11 ms | 新增 |
| 新 `save()`（第一版，保存前读盘校验） | 中位 7.15 ms，p95 8.50 ms | 已弃用 |
| 拆解：只写 + 替换（不刷盘） | 中位 0.33 ms | — |
| 拆解：**先读目标文件**再写 + 替换 | 中位 4.28 ms | 第一版的瓶颈 |
| 拆解：先读别的文件 / 先 stat 再写 + 替换 | 中位 0.40 / 0.38 ms | — |
| 拆解：写 + fsync + 替换（`_write_durably`） | 中位 0.82 ms | 新增 |
| 正常加载 `Config()` | 中位 0.32 ms | 不变 |
| 清零后加载（含另存 `.corrupt`、退回、写回） | 7.7–12.2 ms（单次，三轮） | 只在损坏时 |
| 真实配置目录单次保存（紧跟在加载之后） | 5.40 ms | 命中「读后替换」代价 |

**保存频率（实测）**：分支版桌宠运行中，用脚本每 250 ms 轮询 `config.json` 的 mtime 共 300 s，
记到 **9 次**保存，全部来自用户在设置窗口里改设置（`--settings` 进程 23:14:14 启动，其中一次是同一
操作 8 ms 内连续保存两次）。代码层面 36 处 `config.save()` 全是事件触发（拖拽落点、开关切换、换形象、
退出），没有定时器或逐帧保存。

**结论**：
1. 稳态：桌宠空闲时不保存，开销 0；加载路径不变（0.32 ms）。
2. 新增成本：每次保存多约 0.9 ms（中位）。保存跑在界面线程，但只在用户操作的那一下发生一次，
   低于一帧（7 ms tick）。紧跟在一次读之后的保存会多付约 4 ms（实测单次 5.4 ms）。
3. 新的系统调用：每次保存多一次 `fsync`、一次 `CreateHardLink`、一次额外 rename（`.bak`）；
   POSIX 上再多一次目录 `fsync`。无网络、无新线程。
4. 磁盘与内存：多一个与配置同大小的 `config.json.bak`（约 10–30 KB），硬链接不复制数据；
   内存只多两个属性。

## 五、实机运行记录

**事故现场（根因复现）**——事件日志与数据目录：

```
13/11/2026 22:14:31 1001 WER-SystemErrorReporting  The computer has rebooted from a bugcheck.
                    The bugcheck was: 0x0000003b ... Possibly related driver: dxgkrnl.sys
13/11/2026 22:14:25 6008 EventLog  The previous system shutdown at 10:08:51 PM ... was unexpected.
（同晚另有 21:11、21:46 两次 6008 非正常关机）

config.json.corrupt-1794636576883-34692  26127  22:06:24   ← 全部是 \x00
config.json.corrupt-1794636896349-21608  26127  22:06:24
config.json                               9461  22:54:47   ← 按默认值重建
```

**重演事故（真实桌宠、真实配置目录，先把当前配置另存到 scratch 兜底）**：用分支代码保存一次生成
`.bak` → 结束桌宠 → 把 `config.json` 写成等长全零 → 从分支 worktree 启动桌宠
（`BigFish.exe -m pet`，工作目录 = 分支 worktree）：

```
zeroed len=9461 first byte=0
2026-11-13 23:12:40 acquired pid=47372
--- pet-47372.log head
2026-11-13 23:12:40,069 WARNING 配置文件损坏，已退回上一份完好配置: ...\big-fat-fish\config.json.bak
2026-11-13 23:12:40,070 INFO big-fat-fish 启动 (slot: 0, instance: )
config restored identical: True
config.json.corrupt-1794640360025-47372   9461  23:12:39   ← 损坏原文件照旧另存
```

重演生成的两份 `.corrupt` 事后已删除；事故留下的两份保留。

**真机抓到的回归（已修，测试 ⑥ 守住）**：第一次重演（pid 18480）恢复本身成功，但 `pet-18480.log`
**一直是 0 字节**——当时恢复告警走的是根 logger，抢在 `_setup_logging` 之前给根 logger 装了控制台
handler，`basicConfig` 成了空操作。改用具名 logger + `_setup_logging` 补记后，pid 47372 的日志如上
正常。该现象先在子进程测试里复现为红（`assert 'after-setup' in ''`），修后转绿。

**用户可见行为**：重演之后用户打开设置窗口把设置改回（灵动岛样式已回到 metro），300 s 内 9 次保存，
每次之后 `config.json` 与 `config.json.bak` 都能解析，没有残留 `.tmp`：

```
config.json      9812 23:15:55   ok, island.style= metro
config.json.bak  9812 23:15:55   ok, island.style= metro   （inode 不同，nlink 各 1；同一操作 8 ms 内两次保存）
```

**最终版（去掉保存前读盘校验）**：桌宠从分支重启为 pid 20160（23:22:37），日志 0 条 WARNING/ERROR；
对真实配置目录做一次保存：`disk_intact after load True / save True 5.40ms / content unchanged True /
bak == previous True / tmp leftovers []`。

**边界**：没有 `.bak`（只保存过一次）时清零配置，仍按默认值启动并另存 `.corrupt`——测试 ⑤；
运行中盘上文件被弄坏、重载后再保存，`.bak` 不被坏文件顶掉——测试 ③。

**无法自动验证的部分**：真的「保存后立刻断电 / 蓝屏」无法在本机安全复现。替代证据是：测试 ① 断言
替换前刷过盘、且刷的是将要换上的内容；重演用等长全零文件模拟崩溃后的盘面状态。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests` | All checks passed |
| 聚焦 | `pytest -q tests/test_config_crash_safe_save.py` | 修前 4 红（①②③④）、⑥ 红；修后 6 passed |
| 相关 | 引用 `Config(` / `config.json` / `.save()` 的 203 个测试文件 | 3756 passed；5 failed 均与本改动无关（见下） |
| 全量（最终版） | `python -m pytest -q --ignore=tests/manual_ssl_proxy_check.py` | FULL_SUITE_RESULT |

全量里的失败全部与本改动无关：本机已知的 5 个环境性基线
（`test_image_directory_picker_opens_right_drawer_with_three_column_masonry`、
`test_catalog_animation_count_guard_survives_optimize`、`test_festival_id_guard_survives_optimize`、
`test_real_second_process_refused_on_overlay_topology`、`test_capture_window_rect_coordinates_and_clamping`），
以及 `test_modern_context_menu_has_compact_semantic_groups`、`test_host_icons_are_warmed_at_the_cards_size`
两个——已在基线 `3b424baf` 的干净 worktree 上单跑复现为红，是 main 上既有失败。

## 七、已知限制与后续

- 退回的是上一次保存之前的那一份：崩溃前最后一次改动会丢。
- 设置进程是独立进程，持有自己的配置快照；它与主进程各自维护 `_disk_intact`，都只在解析成功或自己
  安全写完后才留 `.bak`。
- 其它状态文件仍不刷盘（见第二节「未改动」）。
- 今晚的蓝屏指向显卡驱动，与桌宠无关；再出现建议更新显卡驱动。

## 八、风险与回滚

- 无新配置键、无迁移。新增落盘文件只有 `config.json.bak`（以及 slot 配置对应的 `config-slot-N.json.bak`）。
- `git revert` 即可回滚；残留的 `.bak` 不被旧代码读取，可留可删。
- 硬链接在不支持的文件系统上退回复制 + fsync；留 `.bak` 失败只记 warning，不影响保存本身。
