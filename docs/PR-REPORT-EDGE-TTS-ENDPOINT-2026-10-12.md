# PR 报告：语音合成端点被拒时自动换端点（整点报时「语音合成失败」）

> **基线**：`3cb5a8b`（feat(session-card): 会话小鱼详情卡的配色方案）
> **分支**：`feature/claude-session-fish`　**日期**：`2026-10-12`
> **范围**：5 个文件（实现 2、测试 1、文档 2 含本报告）
> **关联**：上游 [rany2/edge-tts#490](https://github.com/rany2/edge-tts/issues/490)；
> 联网功能的排查约定见 [`NETWORK-PROXY-AND-VPN-2026-09-22.md`](NETWORK-PROXY-AND-VPN-2026-09-22.md)

## 一、核心特性

用户反馈：整点报时不出声，桌宠弹气泡「语音合成失败（edge-tts 合成失败 →
zh-CN-XiaoyiNeural 第1次: …）」。

**根因不在桌宠，在服务端。** 微软把「大声朗读」的旧合成端点关了：对
`wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1` 的合成请求，
WebSocket 握手一律返回 403。桌宠用的 edge-tts 7.2.8 已是 PyPI 上的最新版，仍指向这个
端点。上游在 2026-10-10 有人报告同一现象（issue #490），多个国家的用户复现，截至本报告
没有发布修复版。

排查时逐条排除了本机原因（证据见 §五）：

| 怀疑对象 | 结论 | 依据 |
|---|---|---|
| 系统代理 / VPN | 不是 | 注册表 `ProxyEnable = 0`，没有代理环境变量 |
| 本机时钟（请求里有按时间算的令牌） | 不是 | 本机比服务器慢 2.6 秒 |
| edge-tts 版本旧 | 不是 | 已装 7.2.8，即最新 |
| 桌宠的调用方式 | 不是 | 脱开桌宠、直接用库合成，同样 403 |
| 某个音色下架 | 不是 | 中文、英文音色都 403；音色列表接口正常（322 款） |

**改法**：握手被拒（HTTP 401 / 403）时，把合成端点换成微软的新端点
`wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1` 再试一次。这是上游
issue 里多人验证过的做法，本机实测可用。

**红线 / 不变量**

- 默认端点能用时什么都不做（`test_a_working_default_endpoint_is_left_alone`）——上游
  发了修复版之后这段代码自然不再触发，不需要回头删。
- 只有「握手被拒」才换端点；超时、5xx、参数错误照旧走原来的重试与报错
  （`test_other_failures_do_not_trigger_an_endpoint_switch`）。
- 两个端点都不通时仍然如实报「合成失败」，不留空文件
  （`test_when_both_endpoints_refuse_…`）。

## 二、修改文件说明

增删取自 `git diff 3cb5a8b --numstat`。

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/edge_tts_endpoint.py`（新增） | +83 / −0 | `is_rejected(exc)`：只看异常上的 HTTP 状态码是不是 401 / 403，不匹配错误文字。`switch()`：把 `edge_tts.communicate.WSS_URL` 在「库自己的端点」和「新端点」之间对调，返回是否真的换了。`reset()` 供测试恢复。`edge_tts` 只在函数里导入，不改变它的懒加载 |
| `pet/voice_chime_service.py` | +19 / −7 | `_TTSWorker._synthesize`：合成失败时若是握手被拒且成功换了端点，清掉半截文件后原地再合成一次；否则原样抛给外层的重试循环 |

桌宠里所有语音合成（整点报时、点击台词朗读、节日语音、设置页试听）都经过
`_TTSWorker._synthesize` 这一个入口，所以一处修改全部覆盖。

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_edge_tts_endpoint.py`（新增） | +146 / −0 | 9 条：被拒后换端点并成功、换过之后后续合成直接用新端点、新端点日后被拒会换回去、默认端点可用时不动、两个都不通时如实失败且不留空文件、3 种非握手失败不触发切换、状态码判定 |

### 未改动

`requirements.txt` 里 `edge-tts>=6.1.10` 没有改：已装的就是最新版，改版本约束解决不了
问题。音色列表（`edge_tts.list_voices`）走的是 HTTPS 接口，实测正常，没有动。

## 三、实现要点

**为什么不直接把端点改成新的。** 两点考虑：上游迟早会发修复版，那时库自己的默认值
才是权威；另外 issue 里有人观察到新端点的令牌格式也在变化（未证实）。所以只在
**确实被拒**时切换，并且切换是双向的——哪边通用哪边。

**为什么按状态码而不是错误文字判断。** 错误文字是 aiohttp 拼的
（`403, message='Invalid response status', url=…`），随库版本会变；`status` 属性是它的
结构化字段。

**切换是进程级的。** 端点是 edge-tts 模块里的一个全局变量。换过之后本进程后续的合成
都直接用新端点；重启后第一次合成会再撞一次旧端点（约 1 秒的代价，见 §四）。没有把
「哪个端点通」存到配置里——这个事实随服务端变化，存下来反而会过时。

## 四、性能分析

**方法**：一次性脚本（会话内，未入库）用真实网络调用 `_TTSWorker.run()`，逐次计时。
环境：Windows 11 10.0.26300，Python 3.13.15，edge-tts 7.2.8，无代理。

| 指标 | 实测 | 归属 |
|---|---|---|
| 进程内第一次合成（旧端点被拒 → 换端点 → 成功；含首次导入 edge-tts） | 2.22 s | 新增路径，每次启动后一次 |
| 之后的合成（直接用新端点，n=3） | 1.01 / 0.84 / 0.76 s | 既有路径 |
| 修复前一次整点报时从开始到放弃 | 约 3.5 s（4 次握手全部 403：00:00:06.3 → 00:00:09.8），结果是失败气泡 | 对照 |
| 新测试文件 | 9 条，与既有报时测试合计 53 条 1.35 s | — |

**结论**：① 默认端点可用时没有任何额外开销（没有多余的判断之外的工作）；② 被拒时多一次
握手往返，实测首次合成比后续多约 1.2–1.5 秒，其中一部分是 edge-tts 的首次导入，没有
拆开测；③ 网络上多了一个目的主机 `api.msedgeservices.com`（微软的服务，与旧端点同一
用途），没有新线程、没有新的磁盘写入；④ 内存只多一个记住库原端点的字符串。

## 五、实机运行记录

**问题的现场**（桌宠自己的日志，连续 4 个整点全部失败）

```text
pet-47704.log  2026-10-11 21:00:15  语音报时合成失败
pet-37912.log  2026-10-11 22:00:18  语音报时合成失败
pet-42656.log  2026-10-11 23:00:06  语音报时合成失败
pet-38656.log  2026-10-12 00:00:06  WARNING edge-tts 合成失败（zh-CN-XiaoyiNeural 第1次）：403, message='Invalid response status',
               url='wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=…'
```

更早的日志里没有报时记录可比，「此前是否正常」本报告无法确认；上游 issue 的开帖时间是
2026-10-10。

**脱开桌宠复现**（直接调 edge-tts）

```text
edge-tts 7.2.8 | SEC_MS_GEC_VERSION: 1-143.0.3650.75
list_voices: ok, 322 voices, 0.6s
synthesize zh-CN-XiaoyiNeural FAILED: WSServerHandshakeError 403, message='Invalid response status', …
synthesize en-US-AriaNeural FAILED: WSServerHandshakeError 403, message='Invalid response status', …
local clock minus server clock: -2.6 s
ProxyEnable    REG_DWORD    0x0
```

**修复后，走桌宠自己的合成线程**（真实网络）

```text
WARNING 语音合成端点 speech.platform.bing.com 拒绝了握手，改用 api.msedgeservices.com
[0] zh-CN-XiaoyiNeural   rate=+0%  pitch=+0Hz: OK in 2.22s, 18144 bytes, mp3 header=fff3
[1] zh-CN-XiaoyiNeural   rate=+10% pitch=+5Hz: OK in 1.01s, 11376 bytes, mp3 header=fff3
[2] en-US-AriaNeural     rate=+0%  pitch=+0Hz: OK in 0.84s, 12096 bytes, mp3 header=fff3
[3] zh-CN-XiaoxiaoNeural rate=+0%  pitch=+0Hz: OK in 0.76s, 11808 bytes, mp3 header=fff3
endpoint now: wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1
```

带着非默认语速、音调参数的请求（第 1 条）同样成功，中英文音色都能合成。参数是否真的
改变了听感没有验证（没有听音频，四条的文本也不相同，文件大小不能说明问题）。

**真实桌宠**：`2026-10-12 00:04:52 acquired pid=30048`，已用修复后的代码重启，日志无报错。

**没有验证的部分**

- **没有等到下一个整点听一次真实的报时。** 重启时是 00:05，下一次报时在 01:00。上面的
  验证走的是同一个合成线程类，但不是由桌宠的定时器触发、也没有经过播放环节。需要用户
  在下一个整点确认有声音、没有失败气泡；或在设置页点「试听」。
- 没有听合成出来的音频，只核对了文件大小和 mp3 帧头。
- 新端点能用多久取决于微软，无法验证。
- macOS / Linux 未运行。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests`、`git diff --check` | 通过 |
| 红 → 绿 | `pytest -q tests/test_edge_tts_endpoint.py` | 实现前收集即失败（没有 `pet.edge_tts_endpoint`）；实现后 9 passed |
| 聚焦 + 相关 | `tests/test_edge_tts_endpoint.py tests/test_voice_chime_service.py` | 53 passed（含「模块顶层不得导入 edge_tts」两条既有约束） |
| 受影响时序族满载 3 遍 | — | 不适用：新测试同步执行合成线程的 `run()`，重试间隔打桩为 0，没有真实等待 |
| 全量 | `python -m pytest -q -p no:cacheprovider`（`QT_QPA_PLATFORM=offscreen`，`APPDATA` 指向临时目录） | `4 failed, 4983 passed, 11 skipped in 429.94s`，在最终的代码上运行；4 个失败是这台机器上一直存在的环境性失败（路径超 260、两条子进程输出按 cp1252 解码、多显示器负原点）。这次运行之后只新增了本报告与索引登记，`tests/test_pr_report_discipline.py` 另外单独跑过 |

## 七、已知限制与后续

- **这是绕行，不是根治。** 新端点沿用旧的令牌，issue 里有人指出 Edge 浏览器自己已经在用
  另一种令牌格式；微软若进一步收紧，两个端点都会失败，那时只能等 edge-tts 上游更新。
- 上游发布修复版后应升级 edge-tts；本改动届时不会被触发，可以保留。
- 每次启动后的第一次合成会先撞一次旧端点（约 1 秒）。
- 新端点地址来自上游 issue 里用户的发现，不是微软公开的文档。

## 八、风险与回滚

- **影响面**：所有语音合成；默认端点可用时行为不变。
- **配置 / 落盘**：无新增配置键，无落盘状态。
- **回滚**：`git revert` 即可。回滚后在上游修复前，报时会回到「语音合成失败」。
