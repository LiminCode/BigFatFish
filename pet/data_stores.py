# -*- coding: utf-8 -*-
"""存储表：肥鱼往磁盘上写的每一种东西登记一次，并回答「丢了从哪恢复」（决定见 docs/adr/0015-private-repos-are-home.md）。

**只用标准库、不碰 Qt、不读写任何文件**——这里只有声明和几个纯函数。谁用它：

- 配置全景把每一项画成磁贴（在哪、谁写、恢复来源），把「还没覆盖」的列成待处理；
- 以后的同步器和恢复命令按这张表决定推什么、还原什么；
- 测试拿它当守卫：代码里新出现一个数据文件名却没登记，``tests/test_data_stores.py`` 就红。

**加一种落盘数据 = 在 ``STORES`` 里加一项。** 必须回答的只有一个问题：硬盘没了，它从哪回来？

- ``git``：已经有机制把它放进某个私有仓库（写明哪个仓库、哪个机制）；
- ``rebuild``：能重新算出来或重新下载（缓存）；
- ``disposable``：丢了没有损失（锁、进程标记、日志、自愈的簿记）；
- ``secret`` / ``relogin``：密钥和登录态，各有各的恢复办法；
- ``uncovered``：该留却还只在本机。**必须**写明原因和打算在路线图的哪一步补上——这就是缺口清单。

人写的、AI 写的内容（``content``）和用户的设置（``settings``）只能是 ``git`` 或 ``uncovered``：
它们重算不出来，也不能说「丢了无所谓」。

这张表声明的是**设计**：某项标成 ``git`` 表示有机制能备份它，不表示用户此刻开着那个机制、也不表示上次备份
是什么时候。此刻的实际状态由配置全景的探针去看。

表里的中文说明（``holds``、``reason``）是给读代码的人看的。把它们画到配置全景上的那一步，界面文字要走文案库
（中英文各一份，键按存储的 ``id`` 取），到时把这些说明搬过去，这里只留标识和结构。
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass

#: 归哪个账号。``mixed`` = 个人和公司的内容混在同一个文件里：进任何仓库之前都得先分开（ADR 0003）。
ZONES = ("personal", "work", "mixed")
#: 位置的根。``data`` 是肥鱼自己的数据目录；其余是肥鱼会去写、或替用户照看的别处。
ROOTS = {
    "data": "肥鱼的数据目录（%APPDATA%/big-fat-fish）",
    "home": "这台机器上用户的家目录（只登记其中和 AI 有关的文件）",
    "claude_home": "这台机器上个人 Claude Code 的家目录（~/.claude）",
    "claude_home_wsl": "WSL 里公司 Claude Code 的家目录（~/.claude）",
    "kb_personal": "个人知识库的本地克隆",
    "kb_work": "公司记忆库的本地副本",
    "keyring": "系统钥匙串",
    "os": "操作系统里的登记项（开机自启）",
}
KINDS = ("settings", "content", "state", "cache", "log", "marker", "secret", "login")
RESTORE_SOURCES = ("git", "rebuild", "disposable", "secret", "relogin", "uncovered")
#: 可以进 ``git`` 的仓库：个人的进个人的，公司的进公司的（ADR 0003）。
REPOS = ("kb_personal", "kb_work")


@dataclass(frozen=True)
class Restore:
    """丢了从哪恢复。``reason`` 给人看：为什么是这个来源；``uncovered`` 时是为什么还没覆盖。"""

    source: str
    repo: str = ""              # git：进了哪个仓库（REPOS 之一）
    via: str = ""               # git：靠哪个机制（模块名）
    reason: str = ""
    plan: str = ""              # uncovered：打算在路线图哪一步补（如 "M6"）


@dataclass(frozen=True)
class Store:
    id: str
    zone: str                   # 归哪个账号带
    root: str                   # ROOTS 之一
    patterns: tuple[str, ...]   # 相对根的路径，正斜杠；* 可以跨目录
    kind: str                   # KINDS 之一
    writer: str                 # 谁写它（模块名，或 "user" / "claude_code"）
    holds: str                  # 一句话：里面是什么
    restore: Restore
    code_names: tuple[str, ...] = ()    # 源码里拼这个文件名的写法，模式对不上时在这里补（只给守卫用）


def validate(stores: tuple[Store, ...] | None = None) -> None:
    """表里有不自洽的地方就抛 ``ValueError``（导入时不跑，测试里跑）。"""
    stores = STORES if stores is None else stores
    seen = set()
    for store in stores:
        def bad(message: str, store=store) -> ValueError:
            return ValueError(f"store {store.id!r}: {message}")

        if store.id in seen:
            raise bad("duplicate id")
        seen.add(store.id)
        if store.zone not in ZONES or store.root not in ROOTS or store.kind not in KINDS:
            raise bad("unknown zone, root or kind")
        if not store.patterns or not store.writer or not store.holds:
            raise bad("patterns, writer and holds are required")
        restore = store.restore
        if restore.source not in RESTORE_SOURCES:
            raise bad("unknown restore source")
        if restore.source == "git" and (restore.repo not in REPOS or not restore.via):
            raise bad("a git restore must name the repository and the mechanism")
        if restore.source == "uncovered" and not (restore.reason and restore.plan):
            raise bad("an uncovered store must say why and which roadmap step closes the gap")
        if store.kind in ("content", "settings") and restore.source not in ("git", "uncovered"):
            raise bad("content and settings cannot be rebuilt or thrown away")
        if (store.kind == "secret") != (restore.source == "secret"):
            raise bad("secrets, and only secrets, restore as 'secret'")
        if (store.kind == "login") != (restore.source == "relogin"):
            raise bad("logins, and only logins, restore as 'relogin'")


def match(root: str, path: str) -> Store | None:
    """``root`` 下的相对路径 ``path`` 属于哪一项；都不认得返回 ``None``。几项都匹配时取写得最具体的那条模式。"""
    best, best_weight = None, -1
    for store in STORES:
        if store.root != root:
            continue
        for pattern in store.patterns:
            if fnmatch.fnmatchcase(path, pattern):
                weight = len(pattern.replace("*", ""))
                if weight > best_weight:
                    best, best_weight = store, weight
    return best


def unregistered(root: str, paths) -> list[str]:
    """``paths`` 里表不认得的那些，保持原来的顺序。配置全景拿它报「数据目录里有没登记的文件」。"""
    return [path for path in paths if match(root, path) is None]


def gaps() -> tuple[Store, ...]:
    """该留却还只在本机的那些：缺口清单。"""
    return tuple(store for store in STORES if store.restore.source == "uncovered")


_PLACEHOLDER = re.compile(r"\{[^}]*\}")


def accounts_for(literal: str) -> bool:
    """源码里的一个文件名字面量有没有着落：属于某项存储，或者在 ``NOT_STORES`` 里。

    f-string 的占位符当成通配（``config-{slot}.json`` → ``config-*.json``）。只比文件名，不比目录。
    """
    name = _PLACEHOLDER.sub("*", literal)
    if name in _NOT_STORE_NAMES:
        return True
    for store in STORES:
        if name in (_PLACEHOLDER.sub("*", written) for written in store.code_names):
            return True
        for pattern in store.patterns:
            last = pattern.rsplit("/", 1)[-1]
            if last == "*":                 # 「整个目录」这种模式不算数：不然随便一个文件名都有了着落
                continue
            if name == last or fnmatch.fnmatchcase(name, last):
                return True
    return False


def _disposable(reason: str) -> Restore:
    return Restore("disposable", reason=reason)


def _rebuild(reason: str) -> Restore:
    return Restore("rebuild", reason=reason)


def _gap(reason: str, plan: str = "M6") -> Restore:
    return Restore("uncovered", reason=reason, plan=plan)


def _claude_home(zone: str, root: str, suffix: str, who: str) -> tuple[Store, ...]:
    """一个 Claude Code 家目录里要登记的东西。个人的（Windows）和公司的（WSL）结构一样，各登记一遍。"""
    return (
        Store(f"claude_settings{suffix}", zone, root, ("settings.json", "settings.local.json", "keybindings.json"), "settings",
              "claude_code / user / agent_link（只写 hooks 段）", f"{who} Claude Code 的设置：模型、权限、hooks、启用的插件",
              _gap("Claude Code 自己的设置，现在没有任何机制把它放进仓库")),
        Store(f"claude_md{suffix}", zone, root, ("CLAUDE.md",), "content",
              "user / memory_distill（只写受管块）", f"{who}全局规矩：用户自己写的，加上蒸馏写进去的受管块",
              _gap("受管块能从条目库重新生成，用户自己写的那部分没有副本")),
        Store(f"claude_memory{suffix}", zone, root, ("projects/*/memory/*.md",), "content",
              "claude_code / memory_distill（distill-*.md）", f"{who}各项目的记忆文件：AI 自己记的，加上蒸馏落进去的",
              _gap("AI 自己写的记忆只在本机；目录名按项目的绝对路径编码，换机器要记路径映射")),
        Store(f"claude_skills{suffix}", zone, root, ("skills/*", "agents/*", "commands/*", "scripts/*", "plans/*"), "content",
              "user / claude_code", f"{who}的技能、子代理、斜杠命令、脚本",
              _gap("用户和 AI 攒下来的做法，现在只在本机")),
        Store(f"claude_plugins{suffix}", zone, root, ("plugins/installed_plugins.json", "plugins/*"), "cache",
              "claude_code", f"{who}装的插件本体", _rebuild("可以从插件市场重装；启用了哪些记在 settings.json 里")),
        Store(f"claude_transcripts{suffix}", zone, root, ("projects/*/*.jsonl", "history.jsonl", "projects/*"), "log",
              "claude_code", f"{who}会话原文和它的附件（工具结果、子代理记录、截图）",
              _disposable("有意不备份（ADR 0015）：量大、私密，要留下的东西由蒸馏提取成条目")),
        Store(f"claude_login{suffix}", zone, root, (".credentials.json",), "login",
              "claude_code", f"{who} Claude 账号的登录凭据", Restore("relogin", reason="换机器后重新登录")),
        Store(f"claude_scratch{suffix}", zone, root,
              ("file-history/*", "shell-snapshots/*", "sessions/*", "cache/*", "backups/*", "paste-cache/*", "debug/*",
               "session-env/*", "ide/*", "downloads/*", "chrome/*", "daemon/*", "spares/*", "state/*", "*.bak", "*.bak2",
               ".last-*", "settings.json.before-*"), "state",
              "claude_code", f"{who} Claude Code 的运行期簿记和临时文件", _disposable("Claude Code 自己会重建")),
    )


#: ──────────────────────────────────────────────────────────────────────────────────────────────
#: 表。顺序只为好读：先是肥鱼的数据目录，再是肥鱼会去写或替用户照看的别处。
#: ──────────────────────────────────────────────────────────────────────────────────────────────
STORES: tuple[Store, ...] = (
    # ── 设置 ──
    Store("config", "personal", "data", ("config.json",), "settings", "config", "肥鱼的全部设置（不含密钥）",
          Restore("git", repo="kb_personal", via="config_backup",
                  reason="「常规 → 配置备份」把它推到个人知识库仓库的 .big-fat-fish/config.json；默认关着，要用户打开")),
    Store("config_slots", "personal", "data", ("config-*.json",), "settings", "config / overlay_spawn_state",
          "每只分身自己的设置和位置", _gap("配置备份只管主配置，分身的没带上")),
    Store("config_local_copies", "personal", "data", ("config.json.bak", "config.json.corrupt-*", "config.json.before-*",
                                                      "config-*.json.bak", "config-*.json.corrupt-*"), "state",
          "config / slot_manager / config_backup", "设置的本机保险副本：上一份完好的、损坏时另存的、恢复前留底的",
          _disposable("只在这台机器上有用；主配置回来了它们就没用了")),
    Store("config_backup_state", "personal", "data", ("config-backup-state.json",), "state", "config_backup",
          "配置备份的簿记：推到哪、上次什么时候、指纹", _disposable("第一次备份或恢复时重新生成")),
    # ── 人和 AI 写下的内容 ──
    Store("distill_entries", "personal", "data", ("memory-distill/entries.json",), "content", "memory_distill_sink",
          "审核通过的个人侧记忆条目：受管块和知识库那篇都从它生成",
          _gap("生成出来的那篇笔记进了个人知识库，但条目库本身没有；没有代码能从笔记还原条目")),
    Store("distill_entries_work", "work", "data", ("memory-distill/entries-work.json",), "content", "memory_distill_sink",
          "审核通过的公司侧记忆条目",
          _gap("生成出来的那篇笔记进了公司记忆库，但条目库本身没有；没有代码能从笔记还原条目")),
    Store("distill_proposals", "mixed", "data", ("memory-distill/proposals.json",), "content", "memory_distill_run",
          "蒸馏出的全部提案：待审的、通过的、拒绝的（拒绝过的标题会喂给下一次蒸馏）",
          _gap("待审的提案丢了就要重新蒸馏；个人和公司的混在一个文件里，进仓库前要先分开")),
    Store("chat_sessions", "personal", "data", ("sessions/*.json", "sessions/*", "sessions-*/*.json", "sessions-*/*"), "content",
          "chat.session_store", "和肥鱼的聊天记录", _gap("只在本机；要不要进仓库还没定")),
    Store("todo_items", "personal", "data", ("todo_items.json", "todo_items-*.json"), "content", "todo_reminder",
          "待办事项", _gap("只在本机")),
    Store("message_log", "personal", "data", ("message-log.json",), "content", "message_log",
          "肥鱼说过的话，最近 200 条", _gap("只在本机；要不要进仓库还没定")),
    Store("island_icons", "personal", "data", ("island-icons/*",), "content", "settings_island_icon",
          "用户给灵动岛挑的头像图片（缩小后的副本）", _gap("原图在用户自己手里，这份副本只在本机")),
    Store("user_assets", "personal", "data", ("characters/*", "sounds/*"), "content", "user",
          "用户自己放进来的角色包和点击音效，肥鱼只读", _gap("用户放进来的文件，只在本机")),
    Store("session_history", "personal", "data", ("claude-session-history.json",), "state", "claude_session_history",
          "最近的 Claude Code 对话列表和置顶", _gap("列表能从会话记录补回来，置顶是用户设的，补不回来")),
    # ── 自愈的簿记 ──
    Store("distill_state", "mixed", "data", ("memory-distill/cursors.json", "memory-distill/distill-state*.json",
                                             "memory-distill/backups/*", "memory-distill/*"), "state",
          "memory_distill / memory_distill_run / memory_distill_sink",
          "蒸馏的簿记：读到哪了、上次什么时候跑的、改 CLAUDE.md 之前的留底", _disposable("丢了只是从头再读一遍会话记录")),
    Store("distill_candidates", "mixed", "data", ("memory-distill/candidates/*.jsonl",), "cache", "memory_distill",
          "从会话记录里摘出来、等着蒸馏的用户原话（含公司侧内容），滚动 90 天",
          _disposable("有意只留本机（ADR 0015 不备份会话原文）；会话记录还在就能重新摘")),
    Store("assistant_state", "personal", "data", ("personal-briefing.json", "activity.json", "file_eaten_stats.json",
                                                  "session-fish.json", "shuffle-state.json", "proactive_screen_*"), "state",
          "personal_briefing / activity_log / file_eater / session_fish_decisions / shuffle_bag / proactive_limiter",
          "各功能自己的簿记：最新一份个人简报、活跃时长、喂食统计、关掉的小鱼、洗牌、看屏幕的冷却",
          _disposable("每天重新生成或自己长回来")),
    Store("work_state", "work", "data", ("work-briefing.json", "slack-watch.json", "work-notes.json"), "state",
          "work_briefing / slack_watch / work_notes", "公司侧功能的簿记：最新一份工作简报、Slack 关注的上次结果、笔记的提醒时间",
          _disposable("每天重新生成；笔记本身在公司记忆库里")),
    # ── 缓存 ──
    Store("knowledge_base_copy", "personal", "data", ("knowledge-base/state.json", "knowledge-base/*"), "cache",
          "chat.knowledge_base", "个人知识库仓库下载到本机的只读副本，给聊天时查", _rebuild("从 GitHub 重新下载")),
    Store("voice_cache", "personal", "data", ("voice_chime_cache/*", "self_talk_voice/*", "sounds_cache/*"), "cache",
          "voice_chime_service / self_talk_voice / click_sound", "合成过的语音和转码过的音效", _rebuild("用到时重新合成")),
    Store("lyrics_cache", "personal", "data", ("lyrics_cache/*.json",), "cache", "music_lyric", "查到过的歌词",
          _rebuild("用到时重新查")),
    Store("probe_cache", "personal", "data", ("harness_probe_cache.json", "balance_cache.json"), "cache",
          "harness_launcher / app", "探测结果的短期缓存", _rebuild("下次用到时重新探")),
    Store("panorama_snapshot", "personal", "data", ("panorama/*",), "cache", "panorama.render",
          "配置全景的离线快照", _rebuild("再点一次「配置全景」")),
    # ── 日志、锁和标记 ──
    Store("logs", "personal", "data", ("pet-*.log*", "pet-overlay-gate.log"), "log", "app / overlay_instance_gate",
          "运行日志", _disposable("排障用，7 天后自己清")),
    Store("agent_events", "mixed", "data", ("agent-events/*.jsonl", "agent-events/*"), "log", "claude_code 的 hooks / agent_link",
          "Claude Code 的 hooks 写进来的事件流，和肥鱼每次启动重写的 hook 脚本", _disposable("事件看完就没用了；脚本每次启动重写")),
    Store("runtime_markers", "personal", "data",
          ("overlay-instance.lock", "settings.lock", "overlay-active-pets.json", "overlay-settings-command.json",
           "migration-spawns.done", "agent-hooks-refresh.pending", "pet-runtime-*.json", "runtime-*.json", ".migration_staging/*"),
          "marker", "overlay_instance_gate / slot_manager / overlay_spawn_state / overlay_settings_command / config",
          "进程锁、进程标记、进程间的一次性指令、迁移做没做过的记号", _disposable("只对正在跑的这一次有意义"),
          code_names=("{}{}-slot-{}.json",)),
    # ── 肥鱼数据目录之外 ──
    *_claude_home("personal", "claude_home", "", "个人"),
    *_claude_home("work", "claude_home_wsl", "_wsl", "公司"),
    Store("claude_json", "personal", "home", (".claude.json",), "settings", "claude_code",
          "个人 Claude Code 的账号信息、MCP 服务器、各项目的信任与历史",
          _gap("MCP 服务器的配置在这里面，现在只在本机")),
    Store("kb_personal_repo", "personal", "kb_personal", ("*",), "content", "user / personal_vault / memory_distill",
          "个人知识库：笔记、灵感、蒸馏生成的那篇记忆",
          Restore("git", repo="kb_personal", via="personal_vault", reason="它本身就是私有仓库的克隆，肥鱼写完就提交并推送")),
    Store("kb_work_repo", "work", "kb_work", ("*",), "content", "work_notes / slack_watch / memory_distill",
          "公司记忆库：工作笔记、Slack 关注存下来的、公司侧蒸馏生成的那篇记忆",
          Restore("git", repo="kb_work", via="work_notes", reason="它本身就是公司私有仓库的副本，git 在 WSL 里跑")),
    Store("api_keys", "personal", "keyring", ("provider/*", "connector/*"), "secret", "chat.models.SecretStore",
          "各模型服务的 API Key、GitHub Token",
          Restore("secret", reason="定下的做法是加密后放个人私有仓库、主钥放密码管理器（ADR 0015）；还没实现，现在只在钥匙串里",
                  plan="M6")),
    Store("autostart", "personal", "os", ("Run/*",), "state", "autostart", "开机自启的登记项",
          _rebuild("设置里记着用户开过（autostart_wanted），换机器后会提醒重新打开")),
)

#: 源码里出现、长得像数据文件、但**不是**肥鱼落盘的数据：别家程序的文件、随包发的资源、文案键、临时目录里的东西。
#: 每条写一句它是什么。占位符写成 ``{}``（和守卫从 f-string 里读出来的样子一致）。
NOT_STORES: dict[str, str] = {
    ".backoff.json": "帧序列缓存里的退避标记：在角色包目录下，不在数据目录，能重新转换",
    ".converting.lock": "帧序列转换时的锁：在角色包目录下",
    "meta.json": "帧序列缓存的元数据：在角色包目录下，能重新转换",
    "manifest.json": "角色包自带的清单：随包发的资源，只读",
    "move_strides.json": "角色包自带的步幅表：只读",
    "text_clips.json": "角色包自带的文字片段：只读",
    "{}.{}.json": "随包发的台词预设（persona_presets/<模式>.<语言>.json）：只读",
    "dsh-pet-media-meta-cache.json": "素材元数据缓存：在系统临时目录里，丢了重新探",
    "package.json": "DSH 插件档案里的文件：别家程序的，肥鱼只在用户同意安装桥接插件时改它",
    "opencode.db": "别家程序（OpenCode）的数据库：只读",
    "obsidian.json": "Obsidian 的库登记表：只读，用来判断知识库有没有登记",
    "storage.json": "VS Code 的存储文件：只读，用来找最近的工作区",
    "workspace.json": "VS Code 的工作区描述：只读",
    "wpndatabase.db": "Windows 通知中心的数据库：只读（先复制到临时目录再读）",
    "bridge.install.pending": "一条台词的键，不是文件",
    "wsl.pending": "一条界面文案的键，不是文件",
}
_NOT_STORE_NAMES = frozenset(_PLACEHOLDER.sub("*", name) for name in NOT_STORES)
