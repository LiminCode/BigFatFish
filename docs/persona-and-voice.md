# 台词、人设、气泡与语音

> 肥鱼「怎么说话」是几套**互不相干**的东西：发给模型的对话人设、不经模型的气泡台词模板、各处固定文字，
> 再加语音报时的台词库与合成、气泡里的配图。改口吻之前先确认改的是哪一套。

## 模块

| 文件 | 职责 |
|---|---|
| `pet/chat/prompt.py` | `PromptBuilder.build_messages`：拼 system 消息（人设 + 关于我 + 时间说明） |
| `pet/persona_phrases.py` | 内置预设加载（`builtin_phrases`）、`PhrasePicker`（轮换 + 渲染）、`phrase_for_agent`（专属 → 全局）、`render_template` |
| `pet/persona_presets/*.json` | 内置两套台词的数据：`legacy.json`、`whale_maid.json` 及各自的 `.en.json` |
| `pet/persona_template.py` | 事件 schema 真源（`PARAMETERS` / `EVENT_SOURCES` / `DISPLAY_HINTS` / `CONDITIONAL_PARAMETERS`）；`build_persona_template` 生成导出文档 |
| `pet/agent_link.py`（`_dialogue`）、`pet/app.py`（`_persona_text`） | 两个渲染分派点：Agent 联动气泡 / 余额等应用级气泡 |
| `pet/settings_pet_controls.py` | 设置页台词编辑区：只读预览、「改成我的台词」、模板导入导出 |
| `pet/settings_help.py` | `help_row` / `help_section`：设置页里默认收起的说明节 |
| `pet/voice_chime.py` | 报时纯逻辑（零 Qt、零 edge_tts）：调度、文本、`quote_pool` / `pick_quote`、音色清单 |
| `pet/voice_chime_quotes.py` | 内置台词库 `CHINESE_QUOTES` / `ENGLISH_QUOTES` |
| `pet/voice_chime_service.py` | 调度服务；`_TTSWorker`（**所有**语音合成的唯一入口）；音色校验、缓存、播放 |
| `pet/edge_tts_endpoint.py` | 合成端点握手被拒时换端点 |
| `pet/voice_chime_settings.py` | 设置页「语音报时」，含内置库编辑框 |
| `pet/speech_bubble_text.py`、`pet/speech_bubble.py` | 配图尺寸规则：`natural_image_size`、`image_display_edge` |
| `pet/overlay_shell.py` | 自言自语宿主：配图目录复查、解码缓存（`self_talk_image_cache_edge_for_limit`） |

## 机制与不变量

### 全景：谁在说话

| 哪一套 | 存在哪 | 怎么起作用 | 经过模型 |
|---|---|---|---|
| 对话人设 | `config.json` 的 `chat.default_system_prompt`、`chat.about_user`；全局一份，**不随服务商切换** | 人设三选一（调用方给的 > 角色包自带的 > 设置页的），「关于我」总是追加在后面。影响对话窗、快速对话、灵动岛对话、拖文件解读；「看看屏幕」与主动识屏只带人设 | 是 |
| 气泡台词模板 | `dialogue_mode`（`legacy` / `whale_maid` / `custom`）、`dialogue_phrases`；内置两套在 `pet/persona_presets/` | 固定文字 + 占位符。只管 Agent 联动气泡（开始 / 思考 / 活动 / 审批 / 提问 / 完成 / 出错 / 模型访问失败 / 桥接）与余额结果 | 否 |
| 其他固定文字 | `self_talk_texts`（自言自语）、角色绑定的点击台词、语音报时 / 节日台词 | 各自直接读，**不看表达风格** | 否 |
| 不走人设的 AI 任务 | 各自固定提示词：[公司侧](work-assistant.md)的工作简报 / Slack 关注 / 工作笔记，[个人侧](personal-assistant.md)的个人简报 | 与人设无关 | 是 |

两套「性格」互不影响：选「鲸鱼娘女仆模式」不改对话口吻，改人设也不改气泡。设置页两处各有一节默认收起的说明写着这件事；
说明正文里出现配置键和文件名是有意的。

### 气泡台词：三类内容的归属

| 内容 | 归属 | 位置 |
|---|---|---|
| 内置预设（默认模式 / 鲸鱼娘女仆模式） | 数据文件，随代码分发，只读 | `pet/persona_presets/<mode>.json`，模块导入时读一次 |
| 用户台词（自定义） | 用户数据 | `config.json` 的 `dialogue_phrases`（见 [配置与数据](config-and-data.md)） |
| 便携模板（`persona-phrases/v1`） | 运行时生成，不落盘 | `build_persona_template()`，设置页导出时生成到剪贴板 |

**台词文案不写死在代码里**：改内置口吻就改 JSON；不要新增内嵌文案的 Python 常量。已删除、不要恢复的旧物：
`persona_phrases.py` 里硬编码的 `_PHRASES`、`pet/persona_phrases.json`、`pet/persona_phrases_templates/`。

内置预设是扁平的 `{事件键: [文案…]}`，现在 30 个事件、每个 3 条；载入时清洗成每键 ≤8 条、每条 ≤240 字。
**键集合就是事件词表**（`phrase_keys()`），没有另一份硬编码词表。

### 气泡台词：路由

```
custom              : agents[agent_key][key] → global[key] → 调用方传入的兜底文案
legacy / whale_maid : 内置预设[key]                        → 调用方传入的兜底文案
```

- `legacy` 也是 JSON 预设，**不透传调用方原文案**；默认模式下气泡说什么由数据文件决定。
- 自定义模式下某事件留空，回退到的是代码里的兜底文案，**不是**「默认模式」预设那句（两者措辞不同）。设置页文案已照实写；要改成按预设回退是另一个决定。
- `dialogue_phrases` 是两层：`global` + `agents[agent_key]`（只存差异）。旧式扁平 `{事件: [...]}` 当作 `global`。`Config._normalize_pet_settings` 清洗并删掉空的覆盖。
- 专属层**只在 `custom` 模式读**，且只对把 `agent_key` 传给 `_dialogue()` 的转述事件生效：`start`、`thinking`、`activity.*`、`done.*`、`agent.attention`、`agent.error`。审批 / 提问 / 失败 / 模型访问失败这些「对你说」的事件，以及 `bridge.*`、`agent.missing`、余额，只走 `global`。
- 同一事件多条时轮换，避免同一个键连续重复。
- 占位符只能用该事件在 `PARAMETERS` 里声明的字段，越界会原样露出 `{xxx}`。条件字段（`CONDITIONAL_PARAMETERS`）上游没给时自动隐藏。
- 「请到界面输入文本回答」这类结构引导由 `agent_link._with_dsh_input_hint()` 补上，不随台词被覆盖掉。

### 内置预设的英文版

- `<mode>.en.json` 与中文版键集合一致，占位符不超出中文版用到的。
- `builtin_phrases(mode, language=None)` 缺省取界面语言（见 [界面语言](i18n.md)）：有该语言的文件就**按键覆盖**中文，缺键回退中文那条，整个文件不存在就整套中文（只记 debug）。
- 语言在**渲染时**取，不在加载时取：切换语言后下一条气泡就变，不用重启。`i18n` 在函数里惰性导入，避免导入期循环依赖。
- 事件词表仍只由中文文件定义：英文文件多出来的键不会成为新事件。
- 用户的自定义台词不受语言影响。`agent_link.py` 里的代码兜底文案仍是中文，英文预设键齐全时碰不到。
- 再加一种语言：放 `<mode>.<lang>.json`，登记到 `_PRESET_LANGUAGES`。

### 设置页：只读预览与「改成我的台词」

- 表达风格选内置模式时，逐事件编辑框**只读**地显示 `builtin_phrases(mode)`，专属层下拉置灰，`host._dialogue_preview = True`。
- **红线**：预览期间 `_dialogue_flush_scope` 不写缓冲。所有会把编辑框写回缓冲的路径（切层、保存、导出）都先看这个标志，否则内置台词会混进 `dialogue_phrases`。切回自定义时从缓冲恢复用户原来的台词。
- 「以『X』为底改成我的台词」（`_adopt_builtin_phrases`）：整套内置台词写进 `global` 层缓冲、切到 `custom`、展开折叠框。自定义已有内容时先确认；Agent 专属层不动。
- 导出模板带**当前显示**的台词（内置模式就是内置的，自定义就是用户的 `global` 层）：既是备份，也能发给 AI 改写。导入先切到 `custom` 再写编辑框（否则写进预览会被覆盖），校验 `template` 以 `persona-phrases/` 开头。
- 人设与「关于我」在设置页自成一节「人设与回复」，不放在「模型与连接」里——夹在 API Key 旁边会被当成某个服务商的参数。行 id 没变，搜索与深链接按行 id 找。

### 语音报时的台词库

- `quote_pool(cfg)` = 内置库（用户改过就用改过的）+ 自定义**追加**，去重保序。音色以 `zh` 开头用中文那套，否则英文那套。
- `voice_chime_builtin_quotes_zh` / `_en`：**空串 = 代码里的列表原样**。设置页的编辑框预填整份内置库，保存时若与代码里的一字不差就存空串，改过才整份存下。这样没动过的用户能跟上以后版本新增的句子，改过的以自己那份为准。
- `voice_chime_custom_quotes_zh` / `_en` 是追加，不是替换；想去掉内置里的某句，在内置库编辑框里删。内置库编辑框同样走 `clean_custom_quotes`（去空行、去重、单条 120 字截断）。
- 轮换：按日期序数确定性洗牌出当天的排列，日内按报时次序顺序取。洗牌用自带的 LCG 而不是 `random`，保证排列不随解释器版本漂移（缓存键靠它对得上）。
- 音频缓存键按「文本 + 音色 + 语速 + 音调」哈希；库变了只是新句子第一次要合成，旧文件不删，靠 200 个上限清理。
- 节日提醒的台词库仍只在代码里（`pet/festival_quotes_*.py`），追加语义相同（`festival.quote_pool`），没有做成可编辑。

### 语音合成（edge-tts）

整点报时、点击台词朗读、节日语音、设置页试听都经 `_TTSWorker`，修一处全部覆盖。`edge_tts` 只在合成线程里惰性导入（首次导入约 1.4 秒且常驻内存，而报时默认关），模块顶层只做 `find_spec` 探测。

遇到过两类故障，表现都是「没声音 / 合成失败」，**都不是本机网络问题**：

1. **音色被微软下架 → 服务端回空音频**（`NoAudioReceived`）。配置里存的是「当时有效」的音色，内置清单也只是快照。防线：
   - `resolve_voice()`：配置音色不在已知表里就改用默认音色并提示一次（每进程一次）。它**不联网**；在线音色表缓存 6 小时，只在合成线程里刷新，拉不到就沿用旧表。
   - `_TTSWorker`：每个音色重试 2 次、间隔 1.5 秒（连发请求会被偶发拒绝，间隔几秒逐个重试就成功）；主音色都失败再退默认音色；0 字节产物算失败并立刻删掉。
   - `_cache_hit()`：文件存在**且非空**。`edge_tts.save` 先建文件再写，只判 `exists()` 会把失败留下的 0 字节文件当成缓存，从此播一声静音、不再重试。
2. **旧合成端点握手 403**。`edge_tts_endpoint`：握手被拒（401 / 403）时把 `edge_tts.communicate.WSS_URL` 换到另一个端点，原地再合成一次。
   - 只看异常上的 HTTP 状态码，不匹配错误文字（文字是 aiohttp 拼的，会变）。超时、5xx、参数错误不换。
   - 默认端点能用时什么都不做；切换是双向的，哪边通用哪边。两个都不通时如实报失败，不留空文件。
   - 切换是进程级的、**不落盘**：重启后第一次合成会再撞一次旧端点（约 1 秒）。

### 气泡配图

- 设置键 `self_talk_image_max_edge`（160–800，默认 420）与 `self_talk_image_scale`（百分比，100 = 原始大小）。
- 规则（`natural_image_size`）：一个图片像素对应一个逻辑像素，再乘比例；长边超过上限才等比缩小；**只缩不放**。选「逻辑像素」而不是「物理像素」，是为了同一张图在不同缩放的屏幕上显示一样大。
- 吐气水泡的上限约束的是**整个水泡的宽度**：水泡是固定比例的画布，图片只能放在中间的安全区。安全区比例是量出来的（宽 55%、高 58.5%），不是按几何估的——估成 65% 时小图会被塞进装不下它的水泡里画小。
- 解码缓存按**实际能画到的尺寸**留：`image_display_edge(上限, 样式) × DPR × 1.1`。按上限本身留，吐气水泡里有一大半像素永远画不出来（同一批 72 张图：77 MB 对 25 MB）。有测试守着「缓存留的像素不少于气泡真正画出来的」。
- 解码线程只缩不放，所以缓存里的图要么是原始尺寸、要么已经不小于上限，`min(缓存图尺寸, 上限)` 就是显示尺寸，不用另存原图大小。
- 上限、气泡样式、屏幕缩放、目录内容任一变化时缓存重建一次（都在签名里）。配图目录在每次自言自语前复查（最多每 60 秒列一次），运行期间新放进去的图不用重启就进池。
- 不传上限的调用方走旧的固定框（220×140）：那是旧 `PetWindow` 路径，只修崩溃。

## 设计取舍

- **内置台词只读，可编辑靠复制**：预览只是把内置台词摆进编辑框，真正的编辑是复制成自定义台词。不需要新的存储，也不会出现「改了内置模式但不知道存在哪」的第二个黑箱。
- **不做「内置风格 + 按 Agent 覆盖」的叠加**：专属层只属于自定义模式。
- **人设 / 台词两处只改了说明、没改行为**：留空回退到代码兜底而非默认预设，是既有路由，保持不动。
- **报时自定义台词是追加**：内置库是逐条选过的，加几句自己的不该被迫丢掉它们。
- **不把合成端点直接改成新的**：上游库迟早发修复版，那时库自己的默认值才是权威；新端点地址来自上游 issue 里用户的发现，不是公开文档。所以只在确实被拒时换，上游修好后这段自然不再触发，不用回头删。「哪个端点通」也不存进配置，这个事实随服务端变。
- **配图内存没有硬上限**：标准气泡 + 大上限 + 很多图时缓存能到两百多 MB，设置行的说明里提醒了，没有做按需解码或总量限制。
- 没做：`.avif` 不在支持的后缀里；JPG 的 EXIF 旋转不处理（竖拍照片可能横着显示）。

## 外部格式依赖

| 依赖 | 具体内容（升级 edge-tts 或服务端变化后先核对） |
|---|---|
| edge-tts 内部 | `edge_tts.communicate.WSS_URL`（模块级变量）、`edge_tts.constants.TRUSTED_CLIENT_TOKEN`；结构变了 `switch()` 返回 False，按原错误处理 |
| 合成端点 | 库默认 `wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1`；备用 `wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1?Ocp-Apim-Subscription-Key=<同一个令牌>` |
| 握手异常 | aiohttp `WSServerHandshakeError.status` |
| 音色表 | `edge_tts.list_voices()` 每项的 `ShortName`；`VOICE_OPTIONS` 是它的快照，`DEPRECATED_VOICE_LABELS` 人工维护（新下架的音色会以 id 出现在提示里） |

## 排障

| 症状 | 原因 / 先查什么 |
|---|---|
| 语音没声音，日志 `NoAudioReceived` | **先别怀疑网络**。① `edge_tts.list_voices()` 成功 → 网络与 TLS 没问题；② 换默认音色能合成 → 配的音色下架了，对在线表查；③ 连发失败、间隔几秒重试成功 → 服务端限流；④ 看缓存目录 `voice_chime_cache` 里有没有 0 字节 mp3 |
| 「语音合成失败」，日志里握手 `403` | 端点被关。确认不是本机：系统代理没开、时钟没偏（请求里有按时间算的令牌）、edge-tts 已是最新、脱开肥鱼直接用库同样 403、中英文音色都 403 而音色列表正常。两个端点都 403 只能等上游更新 |
| 每次启动后第一次报时慢约 1 秒 | 先撞了一次旧端点再切换，属预期 |
| 英文界面下气泡还是中文 | 用的是自定义台词（不随语言变），或走到了代码兜底文案（预设缺键） |
| 气泡里露出 `{xxx}` | 台词用了该事件 `PARAMETERS` 没声明的占位符 |
| 换了表达风格，对话口吻 / 自言自语没变 | 本来就不归它管，见「全景」 |
| 自定义某事件留空，出来的不是默认模式那句 | 回退到代码兜底文案，见「路由」 |
| 保存后自定义台词变成了内置那套 | 某条写缓冲的路径漏判 `_dialogue_preview` |
| 报时每天同一时刻总是同一句 | 轮换必须以日期为种子洗整库；按「一天分几段取批次」的写法会把日期抵消掉 |
| 改了内置台词库，升级后看不到新增的句子 | 改过就整份存在 `voice_chime_builtin_quotes_*` 里，以它为准；点「恢复内置」回到空串 |
| 配图发糊 | 缓存目标长边小于实际显示尺寸；查 `image_display_edge` 与样式、DPR 是否进了缓存签名 |
| 新放进目录的图不出现 | 后缀不在 `SELF_TALK_IMAGE_SUFFIXES` 里；或还没到 60 秒一次的目录复查 |

维护时：新增 / 删除事件键要同步 `persona_template.py` 的四张表和四份预设 JSON（`tests/test_persona_presets.py`、`tests/test_persona_template.py`、`tests/test_persona_presets_english.py` 锁着）。已知的小不一致：`bridge.unknown` 在预设里有、设置页没有它的显示名；`balance.loading` 可编辑但没有运行时调用方；聊天窗内的旧设置对话框只能改人设、没有「关于我」。
