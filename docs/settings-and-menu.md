# 设置窗口与右键菜单

> 「肥鱼设置」是一个独立进程里的 Metro 风格窗口（方角磁贴、上下折叠、朝光标倾斜）；右键菜单是一棵用户可编排的布局树，
> 新版样式自画圆角与阴影。本文还收着**设置变更门禁**（新增 / 改动任何持久设置前必读）和已下线入口的清单。

## 模块

| 文件 | 职责 |
|---|---|
| `pet/__main__.py` | `--settings` 分流：最小 `QApplication` + `Config` + `ModernSettingsDialog`，持有 `settings.lock`；**不导入 `pet.app`** |
| `pet/modern_settings_dialog.py` | 设置窗口本体：侧栏能力域、把各页的行按 `setting_id` 重新分节、保存；有行数预算 |
| `pet/theme_tokens.py` | `METRO_TOKENS`（明 / 暗两张令牌表，**唯一的一份**）；`tokens_css()` 把它变成给[配置全景](config-panorama.md)网页的 CSS 变量。不 import Qt |
| `pet/settings_theme_qss.py` | `metro_stylesheet(dark)`：用令牌表填出设置页的 QSS；仍可从这里 import `METRO_TOKENS` |
| `pet/settings_widgets.py` | 共享控件：`tilt_transform` / `TiltButton` / `TiltItemDelegate`、`ToggleSwitch`、`ModernSelect`、`ProviderList`、`SettingsTabContainer`（手风琴）、`SETTINGS_DOMAIN_NAV` |
| `pet/settings_<主题>.py` | 各功能自己的设置行（`settings_tray.py`、`settings_language.py`、`settings_music.py` …），主文件只留几行接线 |
| `pet/settings_focus.py` | 设置已开着时按锁文件的 pid 找到那扇窗并调到前台 |
| `pet/chat/ai_settings_page.py` | AI 页：模型服务列表、API Key、连接测试 |
| `pet/tray_icon.py` | 自定义托盘图标的读取与裁剪（托盘、灵动岛头像共用 `fit_icon_pixmap`） |
| `pet/menu_layout.py` | 菜单布局树：校验、把新版默认项并进用户编排、解析成可渲染的节点 |
| `pet/menu_templates/modern-default-v1.json` | 新版菜单的默认布局树；`modern.json` / `legacy.json` 现在只提供模板切换那一项的文字 |
| `pet/context_menus/registry.py` | 动作注册表 `MENU_ACTIONS`：id → 建造器 / 可用性 / 置灰原因，`ACTION_LABELS`、`ACTION_ICONS` |
| `pet/context_menus/shared.py`、`legacy.py` | 各条目的建造器；旧版菜单的写死顺序 |
| `pet/context_menus/menu_styles/modern.py`、`common.py` | 新版样式（圆角、阴影、描边、勾选层）；两版共用的响应与「点了不关」行为 |
| `pet/settings_menu_layout_editor.py` | 设置 → 菜单 里的编排编辑器 |
| `pet/config.py` | `reload()` 键白名单、`_MENU_LAYOUT_DROPPED_ACTIONS` / `_MENU_LAYOUT_DROPPED_SUBMENUS` |

## 机制与不变量

### 设置是独立进程，单实例

- 主进程 `AppShell.open_settings_process` 用 `python -m pet --settings [--settings-page <域名>] [--instance slot-N]` 拉起；
  关窗即退出，内存全部还给系统。`settings_process_isolation` 关掉才退回进程内对话框。
- 单实例靠配置目录下的 `settings.lock`（`QLockFile`，按 pid 存活判陈旧，崩溃残留不会堵住入口）。
  所有肥鱼共用这一个设置进程。
- 设置已开着时再点「肥鱼设置」：先 `focus_settings_process` 把那扇窗调到前台，调不上来（没找到窗、系统拒绝、非 Windows）
  才弹「已经打开」的通知。pid **从锁文件读**（`QLockFile.getLockInfo`），不记拉起时的 pid：设置进程可能是另一只鱼或上次运行拉起的。
  挑窗按标题含「设置 / settings」，都没有就取该 pid 最前面那扇有标题的窗。前台调用复用 [会话跳转](session-jump.md) 的 `focus_window`。
- 拉起后 5 秒内的连点视为「正在启动」，不双开也不提示。
- 保存后生效的链路：设置进程写盘 → 主进程的配置监视器 → `Config.reload()` → `OverlayShell.refresh_settings()`。
  设置进程自己不会就地刷新（例如换语言要重开设置窗口）。
- `--settings` 路径严禁导入 `pet.app`（会连带载入素材库、ffmpeg、托盘、灵动岛）。

### Metro 视觉

- 令牌只在 `METRO_TOKENS`（`pet/theme_tokens.py`）；明、暗是**二选一**的两张表（不是浅色打底再追加深色），断言令牌的测试要两张都认。
  改一个颜色，Qt 这边和配置全景网页上的控件一起变。
  灵动岛、通知弹窗、用量看板、简报窗口也读这张表。
- 口径：圆角一律 0（含弹出面板、滚动条、搜索框）；磁贴没有描边和阴影，靠底色分层；页标题 30px / 300，节标题 15px / 600；
  侧栏项满宽，选中 = 主题色底白字；按钮透明底 2px 描边；主题色只给选中 / 焦点 / 开着的开关 / 展开表头的左缘。
  完整规范在 `.agents/skills/desktop-pet-ui-style/references/visual-system.md`。
- 页内同级任务用上下折叠的手风琴 `SettingsTabContainer`，不用左右标签。它的类名、`objectName`（`settingsTaskTabs`）和
  `addTab / keys / labels / currentKey / setCurrentKey / key_for_descendant / activate_for_descendant / stack` 不能改：搜索深链和截图脚本按它取页。
  一次只开一页，收起的页只是 `hide`；点开着的那块不收；表头响应 `toggled` 而不是 `clicked`（程序里 `setChecked` 也要能切页）。
- 倾斜：`tilt_transform` 按光标到中心的相对位置做带透视的旋转（悬停 ±4°、按下 ±8° 并缩 1.5%，视距 900px）。
  `TiltButton` 把 QSS 外观原样画在倾斜的画布上，附件走 `_paint_overlay`；列表项用 `TiltItemDelegate`。
  纯视觉：命中、布局、几何不变，没有定时器。设置页里新加按钮用 `TiltButton`，不用裸 `QPushButton`。
- 开关 `ToggleSwitch` 是 44×20 方角；下拉用自绘的 `ModernSelect`（文字放不下时右侧省略），不用 `QComboBox`。

### 行的归属

- 设置窗口建好各页后，`_rebuild_domain_navigation` 按 `setting_id`（`settingRow_<id>`）把所有行搬进侧栏的能力域。
  **没被认领的行会掉进「自动化与联动 → 待分类（开发期）」**，新增一行要同时在目标域里 `claim`。
- 行会被搬家，所以页面代码要持有行对象的引用，不能在自己的页面下 `findChild`。
- 侧栏域名的中文是内部标识（测试、`select_page`、`--settings-page` 都按它认），显示时才翻译；`select_page` 中英文域名都认。
- `modern_settings_dialog.py` 超行数预算时把新内容拆到 `settings_<主题>.py`，不要压行。

### `Config.reload()` 是键白名单

- `reload()` 不是把磁盘上的键全读进来，而是按写死的键列表逐个取。**新增顶层键必须同时加进默认值表和白名单**；
  漏了的表现是 `set` + `save` 都成功、磁盘上也有，下一个 `Config()` 读出来却是默认值。`tests/test_config_schema.py` 的快照守着两处。
- 反过来，把键移出白名单就是迁移：旧值下次加载时丢掉、保存后从文件里消失（`music_player_paths` 就是这样删的）。
- 设置页保存只写自己管的键；已下线入口对应的键（`balance_*` 等）留在用户配置里不会被覆盖。
- 其余读写、备份、损坏恢复见 [配置读写](config-and-data.md)。

### 模型服务列表与 API Key

- 「模型服务」是 `ProviderList`（`QListWidget`），接口与 `ModernSelect` 同名同义，页面里挂在 `provider_combo` 上的增删改逻辑不用动。
  每行「名称 · 模型」，随名称 / 模型输入框实时变；点一行，下面「模型与连接」编辑的就是它。
- 「（使用中）」标的是**盘上的 `active_provider`**，不是当前选中行；选中只表示「正在编辑」。保存时选中的那一项成为 `active_provider`。
- 「添加」复制当前项（同一家服务商换模型最常见），名称全选等着被改。
- Key 存系统钥匙串，条目名 `provider/<id>`（视觉 Key 是 `provider/<id>/vision`）；钥匙串不可用时只在本次运行的内存里，写盘前剔除，
  `reload()` 也不会把内存里的 Key 冲成空。
- Key 输入框打开时遮着填好已存的 Key，「显示 / 隐藏」切明文，换一行自动遮回。保存语义：
  **和已存的一样 → 不重写钥匙串；清空 → 不改（不会删 Key）；改了 → 只写这一项**。
- 视觉 Key 不预填：它的空值有含义（沿用聊天的 Key）。

### 托盘图标自定义

- 配置键 `tray_icon` 存图片的绝对路径（不复制文件）。没填、文件不在、不是图片都静默回到角色头像，设置行的说明会变成「这个文件用不了」。
- 图片只裁透明留白、等比缩放，不拉伸、不裁内容；动图取第一帧。
- `_refresh_tray_icon_once()` 必须先问自定义图片：托盘建造时角色首帧还没解码，有一个轮询等首帧，
  只在建造时用自定义图的话，几百毫秒后会被轮询换回角色头像。
- 改设置即时生效（`refresh_settings()` → `_apply_tray_icon_setting()`）；清空而角色帧未就绪时重新进入轮询。
- 只做了单合成窗拓扑；`PetWindow` 的旧托盘不读这个键。灵动岛头像不受影响。

### 右键菜单：布局树

- 新版菜单每次弹出都重建：`resolve_menu_layout(cfg["context_menu_layout"], …)` → `MENU_ACTIONS.populate`。
  `context_menu_layout` 为 `None` = 用默认树 `modern-default-v1.json`；用户编排是 `layout_id: "user"`、`schema_version: 1` 的同构树。
- 节点三种：`action`（`id` 是注册表里的动作）、`submenu`（`id` / `label` / `children`，**只允许一层**）、`separator`。
  节点在列表里的先后就是顺序；`visible: false` 是隐藏。
- 每个节点可带 `alias`（改名，截到 40 字）和 `icon`（内置图标名、`"none"`，或 `{"kind": "file", "path", "display": "cover" | "contain"}`；
  文件读不出来回到默认图标）。
- **编辑器没有删除，只有隐藏**。所以用户树里「没有」某个动作只可能是「存的时候它还不存在」：解析时把默认树里新出现的动作
  插到模板里最近的兄弟旁边（先找前一个，再找后一个，都没有就追加），不动用户已有的顺序；默认树里 `visible: false` 的新项并进去也是隐藏的。
- 首尾和连续的分隔线在解析后归一；能力不可用的动作不渲染，可用但未启用的置灰并带原因提示。
- 「肥鱼设置」「退出」永远在：被藏掉或丢了会补到末尾。树里有重复动作、子菜单超过一层或 `schema_version` 不是 1 时，
  整棵退回只有这两项的兜底菜单。
- 模板自带的子菜单名（「肥鱼控制」「工具与帮助」）会被复制进用户编排；显示时走 `default_label`，名字还是模板原文才翻译，见 [界面语言](i18n.md)。
- `context_menu_template` 只有 `modern` / `legacy`，非法值回 `modern`。旧版是 `legacy.py` 里写死的扁平菜单，不读布局树，无图标。

### 右键菜单：增删条目

- **加一项**：`registry.py` 里 `_specs`、`ACTION_LABELS`、`ACTION_ICONS` 各一条；两张语言表加 `menu.action.<id>`；
  `modern-default-v1.json` 放到想要的位置；旧版要有就在 `legacy.py` 里加一行。用户已保存的编排会按上面的规则自动补上。
- **删一项**：注册表、建造器（`shared.py`）、`legacy.py`、`modern-default-v1.json`、托盘菜单同时删，
  **再把 id 写进 `_MENU_LAYOUT_DROPPED_ACTIONS`**（整组子菜单写进 `_MENU_LAYOUT_DROPPED_SUBMENUS`，连壳清掉）。
  不写的话用户旧编排里残留的节点会被菜单编辑器一直回存成「此平台不可用」。同名 id 将来重新引入时从集合里删掉即可。
- 按固定下标插入的条目（「Agent 联动」里的 `Claude Code (WSL)`）在删掉前面的项后会错位，删条目时顺手查。

### 右键菜单：圆角、阴影与交互

- 新版菜单窗口必须带 `WA_TranslucentBackground` + `FramelessWindowHint` + `NoDropShadowWindowHint`，
  子菜单经 `inherit_menu_style` 走同一个函数。原因见「外部格式依赖」。
- 阴影自画：菜单四周留 `SHADOW_MARGIN = 10px` 透明边距（QSS `margin`），`ModernShadowLayer` 只在边距里画跟着圆角走的软阴影；
  描边 `ModernHairlineBorder` 和勾选层 `ModernCheckLayer` 都按 `menu_body_rect()` 定位。
  代价：菜单矩形每边大 10px，本体比 `exec(pos)` 的点偏 10px，点在边距里不会关菜单。
- 半透明只给 QSS 背景色写 alpha，不设整窗 opacity（否则文字、图标一起变淡）。
- 勾选状态由**一个菜单级绘制层**按 `QAction.isChecked()` 画在右侧固定槽位，不给每个动作挂子控件。
- 两版共用 `ResponsiveMenuStyle`（长菜单可滚动、同级子菜单切换不卡）和「点叶子项不关菜单」的过滤器；
  要点了就关的条目建造时传 `close_on_trigger=True`。
- 子菜单用 `add_submenu` 建（显式带父对象并由父菜单持有引用）：PySide 里 `addMenu()` 返回的包装对象和之后取到的不一定是同一个。
- 菜单内容永远 LTR；弹在肥鱼左边还是右边只改坐标，不改布局方向。

### 已下线的入口与有意留下的代码

口径：**只摘入口，不删能力**；用户配置里已有的值原样留着。

| 下线的入口 | 留下的（有意） |
|---|---|
| 右键 / 托盘的「DeepSeek 余额」「DeepSeek Harness」「打开网页版 DeepSeek」；设置页「余额与服务状态」一节、「点击显示余额」、「随肥鱼启动 dsh 服务 / 自启目标」；灵动岛「卡片内容」里的余额选项 | `pet/balance.py`、`pet/harness_launcher.py`、`AppShell._maybe_autostart_harness`（读 `harness_autostart`，默认关）、`click_show_balance` 的点击路径、`balance_*` / `harness_*` 配置键；`dynamic_island.card_source` 的 `balance` 值仍认，`auto` 在没开 Claude Code 联动时仍回落到余额卡片 |
| 「Agent 联动」里的 DSH 开关 | `DshMonitor` 与 `agent_link.dsh`：已经开着的人监视器照跑，要关只能改配置文件。彻底删 DSH 联动是另一件事 |
| 「音乐」子菜单、网易云 / QQ 音乐播放器（找程序的模块、启动扫盘、设置页三行、`music_player_paths`） | 歌词气泡与唱歌联动（读系统媒体会话）；`pet/music_lyric.py` 仍查 QQ 音乐 / lrclib / 网易云三个公开接口（那是查词来源，与播放器无关）；`shared.py` 里的 `add_music_pause / next / prev / quit / lyric_align` 已不在任何菜单里但没删 |
| 「显示本轮消费」「检查更新」「夸克网盘下载」「鼠标穿透」菜单项，设置页左下角版本号 | `__version__` 还在；鼠标穿透的入口在设置页和托盘 |

- 对话窗口风格 `modern` 的显示名是「肥鱼版宽屏」，配置值没变。
- 「YouTube Music」是主菜单单独一项（没有恢复「音乐」子菜单）：用默认浏览器打开首页，**不自动播放**——用户不要，
  而且只打开首页时浏览器还没有媒体会话，没有对象可以发「播放」。要显示歌词得打开「浏览器媒体会话参与歌词」（`music_browser_media_enabled`）。

## 设置变更门禁

适用于新增、移动、重命名、删除或改变任何持久设置，以及改设置页布局、保存语义、平台可见性和依赖关系。
满足全部适用条目才可交付；不适用项要在变更记录里说明原因。

### 准入：什么时候值得进入设置页

候选项必须同时满足：

1. **它是偏好**：表达用户希望以后持续采用的行为，不是一次性命令、当前状态或诊断信息。
2. **低频且跨任务**：不需要在主要交互中频繁切换；高频命令留在右键菜单或任务现场。
3. **有可靠默认值**：未配置时仍能安全、可预测地工作；默认值适合多数用户。
4. **归属唯一**：能归入一个稳定的 `domain_id/group_id`；其他入口只提供搜索别名或深链，不复制开关。
5. **值得让用户决策**：产品无法可靠自动推断，操作系统也没有更合适的全局控制。
6. **契约完整**：已定义支持能力、平台差异、依赖项、保存时机、迁移和恢复策略。

默认不准入：「播放一次」「立即隐藏」「检查更新」这类命令；应用能稳定推断的实现参数；只为暴露内部调试状态的开关；
操作系统已统一管理的 DPI、系统字体、全局辅助功能；没有稳定默认值、迁移方式或失败恢复路径的实验参数。

确需暴露的专家参数进一层 `advanced` 披露并说明风险 / 效果。实验功能必须有明确生命周期、默认关闭、兼容策略和移除条件。

### 准入记录

每个设置至少声明：`setting_id`、`domain_id / group_id`、`title / description / search_aliases`、`default`、
`capability_requirement / platform_availability`、`disclosure_level`（`primary` | `advanced`）、`dependency`、`preview_target`、
`commit_policy`（`immediate` | `on_finish` | `confirm`）、`migration`、`recovery`。

**搬到配置全景页面上的设置，这份记录写在代码里**：`pet/settings_table.py` 的 `GROUPS`（决定见
[ADR 0014](adr/0014-panorama-becomes-the-console.md)）。一个 `Group` 是配置里一个顶层键下的一组设置，绑着那个功能自己的
`normalize`；一个 `Setting` 声明它的 `id`（点号表示字典的下一层）、控件（开关 / 下拉 / 可自填的下拉 / 数字 / 文本 / 长文本）、
可选值、保存时机、披露层级、依赖。读、默认值、校验都不另写：一律走 `normalize`，所以表里的默认值就是 `normalize({})` 的结果。

- 这张表只有声明和纯函数，不碰 Qt。它现在**只登记了工作简报这一组**，这一组只能在配置全景上改
  （入口和写入链路见[配置全景](config-panorama.md)的「改设置」）。
- **搬一组 = 一个 PR 里做三件事**：在 `GROUPS` 里声明；从设置窗口删掉这一组的控件和保存代码（设置窗口保存时就不再碰这个键，
  页面改的值不会被它盖回去）；原处换成 `settings_moved.moved_row(dialog, "<组 id>")`——一行「搬到配置全景了」加一个按钮，
  点了经指令通道（`overlay_settings_command` 的 `open_panorama`）请主进程打开配置全景并翻到这一组。
  这一组的「这个功能怎么运作」说明可以留在原处。右键菜单里的就地开关（工作简报的「工作日自动生成 / 生成时间」）由主进程直接写，
  不会和页面互相覆盖，暂时留着。
- `settings_table.check_changes` 是写入时的校验：哪一项、什么类型、在不在可选值里，以及**功能自己的 `normalize` 认不认**
  （提交的值被它改掉了就拒）。给已登记的功能加设置项时，`normalize` 对不合法值的处理就是这一项的写入校验。
  功能把数字夹在一个范围里的，把那一对范围写进 `Setting.bounds`（单位写 `unit`）：页面画出范围，超了明说 `out_of_range`，
  而不是笼统的「不认」。可选值本身看不懂的（空串、英文档位），用 `Setting.labels` 给它配上文字。
  已搬的组：工作简报、Slack 关注、工作笔记、个人助理。
- `tests/test_settings_table.py` 是守卫：功能的 `normalize` 多给出一个键，却既没在表里声明、也没写进那一组的 `not_editable`
  说明为什么不给改，测试就红；表里的每个可选值存下去再读回来必须还是它；每一项在两张字表里都得有标题。
- 文字不抄第二份：从设置窗口搬过去的项直接沿用原来的文案键（`Setting.text` / `.hint`），只有新出现的才用
  `settings.<组>.<id>` 这个默认的键。
- 版本（`settings_table.version`）是一组**生效值**的指纹，给以后的写入链路判断「页面看到的值是不是旧了」用。

新增一级能力域还要证明：它代表长期独立的用户目标，预计至少有两个稳定设置组，且放进现有域会显著降低可发现性。
平台名称、代码模块和短期功能品牌不能单独构成能力域。

### 准出：修改设置页何时可交付

- **§1 契约**
  - 归属、文案、默认值、依赖、能力条件、披露层级和保存语义均已评审。
  - 配置向前 / 向后迁移可解释；**旧 key、旧入口和搜索别名有明确去向**。
  - 失败时有默认值、回滚或安全入口，不会让用户无法重新打开设置或退出应用。
- **§2 TDD**
  - 每个行为切片先有能因缺少该行为而失败的 focused test，再以最小实现转绿。
  - 纯规则从公开领域 seam 测；Qt 行为从设置窗口或实际菜单 seam 测，不断言私有调用顺序。
  - 至少覆盖默认值、持久化 round trip、迁移、依赖、平台 capability matrix、搜索 / 深链、保存策略和恢复路径。
  - 相关测试通过；要不要跑全量按 `AGENTS.md` 的风险门定（动了配置迁移、共享模型、平台分支的要跑）；`git diff --check` 通过。
- **§3 布局与可访问性**
  - `compact / standard / wide` 内容宽度下无裁切、遮挡、不可达控件或错误滚动。
  - 系统字体、放大字体、中英文长文案和 High DPI 下按字体度量增高或换行。
  - Tab 顺序、键盘操作、可见焦点、accessible name / description 和焦点恢复可用。
  - 明暗主题下文字、边界、禁用态、hover / pressed / focus 状态可辨认。
  - 动效有明确用途、可中断并尊重系统 reduced-motion；设置表单不用破坏阅读顺序的瀑布流。
- **§4 跨平台**
  - macOS、Windows、Linux 共享 setting ID、默认值、依赖和保存语义。
  - **永久不支持的能力不创建控件；暂不可用的能力保留并解释原因。**
  - capability fake 覆盖三端组合；至少在当前可用平台完成真实 GUI 验收。
  - 交付说明区分「真实平台已验证」和「模型 / CI 已覆盖」，不推断未执行的平台结果。
- **§5 视觉与文档**
  - 受影响页面和菜单有代表性截图：默认、长文本、窄宽度、平台条件、错误 / 禁用态。
  - 实时预览与最终呈现用同一模型，不维护演示专用副本。
  - 改变 Shared UX Contract、Settings System 或 Menu Action Model 时更新 `CONTEXT.md`；只有长期且非显然的工程约束才进 agent 文档。

## 设计取舍

- **倾斜用 painter 变换，不用 `QGraphicsView`**：要的只是「压一下」的反馈，变换不改布局和命中；真 3D 得把控件搬进场景。
- **换控件不换接口**：手风琴沿用旧标签容器的 API，模型服务列表沿用下拉框的方法名——搜索深链、增删改 / 保存逻辑和既有用例都不用动。
- **托盘图标不做缓存、不复制文件**：配置变更不频繁，缓存要处理「文件被替换」；原文件挪走后回到默认是有意的退路。
- **有意没做**：系统 reduced-motion 探测（Qt 没有现成 API，倾斜只有几度且不自动运动）；Metro 的全大写标题和动态磁贴；
  托盘图标「居中裁成方形」；旧的 `ChatSettingsDialog`（`pet/chat/settings_dialog.py`，旧拓扑的 AI 设置）仍是下拉框、Key 框为空；旧版菜单不画软阴影。

## 外部格式依赖

升级 Qt / PySide 后先核对这几条：

- **Windows 分层窗口的判定**（Qt Windows 平台插件 `setWindowLayered`）：只有「surface 带 alpha 且 `FramelessWindowHint`」或「窗口不透明度 < 1」
  才有 `WS_EX_LAYERED`。`QMenu` 是 `Qt.Popup`，没有 Frameless 位，所以只在菜单淡入（不透明度 0 → 1）期间是分层窗口；
  淡入一结束分层被摘掉，圆角外的透明像素合成成黑色。菜单若换成 OpenGL / RHI 表面，分层路径不同，要重新验证。
- **`CS_DROPSHADOW`**：Windows 给弹窗窗口类加的系统阴影只会按窗口矩形画，跟不了圆角，所以要 `NoDropShadowWindowHint` 后自画。
- **PySide 6.12 的 `setWindowFlag(NoDropShadowWindowHint, True)` 不生效**（`windowFlags()` 里没有这一位），要用
  `setWindowFlags(flags | hint)`；Frameless 位用 `setWindowFlag` 正常。
- **`QLockFile.getLockInfo()` 的返回形状**随绑定版本不同（有的第一项是「成功与否」），`settings_process_pid` 两种都处理了。
- Windows 托盘最终显示多大由系统定（通常 16–32px），自定义图标只能填满那个方格，不能让方格变大。

## 排障

| 症状 | 原因 / 先查什么 |
|---|---|
| 改了设置页代码，窗口还是旧样子 | 旧的设置进程还开着（它跑的是拉起时的代码），关掉重开；重启肥鱼时别顺手杀掉带 `--settings` 的进程，里面可能有没保存的改动。肥鱼启动时发现设置窗口已经开着会弹通知提醒这件事 |
| 设置窗口里有一节只剩「到配置全景里改」 | 那一组搬到配置全景了（ADR 0014），只在页面上改；按钮打开配置全景并翻到那一组 |
| 新设置项存得进、读不回 | 键没进 `Config.reload()` 白名单；跑 `tests/test_config_schema.py` |
| 新加的行出现在「自动化与联动 → 待分类」 | `_rebuild_domain_navigation` 里没 `claim` |
| 用户说「API Key 没存上」 | 先查钥匙串条目 `provider/<id>` 在不在：Key 不进配置文件，清空输入框也不会删它 |
| 菜单圆角外四个黑角 | 窗口在淡入后不是分层窗口了：查 `windowFlags()` 有没有 `FramelessWindowHint`。**要等淡入结束（≥ 200ms）再抓屏**，刚弹出时永远看不到；关淡入动画、DWM 圆角偏好都没用 |
| 圆角外一圈直角阴影 | 系统阴影没关掉：查 `NoDropShadowWindowHint`（注意上面 PySide 的坑） |
| 再点「肥鱼设置」只弹通知、窗没上来 | 前置失败的退路：前台是权限更高的窗、非 Windows，或没找到带标题的窗；日志里有「设置窗口没能调到前台」 |
| 自定义托盘图标一闪又变回角色头像 | 首帧轮询把它顶掉了：`_refresh_tray_icon_once()` 没先问自定义图片 |
| 托盘图标看着太小 | 角色不是方的，等比缩进方格后只占 29%～52% 面积；换一张接近方形的自定义图 |
| 删掉的菜单项在编辑器里显示「此平台不可用」 | id 没进 `_MENU_LAYOUT_DROPPED_ACTIONS` |
| 英文界面里某个子菜单名还是中文 | 用户旧编排里存的是更早的模板原名：把那个旧名加进 `SUBMENU_LABEL_KEYS` 的原名元组 |
| 离屏截图里文字全是方块 | 离屏平台没有中文字体，只能核布局与配色；要看字用 `QT_QPA_PLATFORM=windows` 跑 `scripts/capture_settings_pages.py` / `capture_context_menu.py` |
| 歌词提示让用户去「音乐 → 歌词对齐」 | 那个菜单已下线，提示文案（`lyrics.ui.player_doesn_t_report_playback`）没跟着改；只在播放器不上报进度时出现 |
