# -*- coding: utf-8 -*-
"""存储表：肥鱼往磁盘上写的每一种东西登记一次，并回答「丢了从哪恢复」（决定见 docs/adr/0015-private-repos-are-home.md）。

**只用标准库、不碰 Qt、不读写任何文件**——这里只有声明和几个纯函数。谁用它：

- 配置全景把它们画成磁贴（在哪、谁写、恢复来源），把「该留却只在本机」的列成待处理；
- 以后的同步器和恢复命令按这张表决定推什么、还原什么；
- 测试拿它当守卫：代码里新出现一个数据文件名却没登记，``tests/test_data_stores.py`` 就红。

**加一种落盘数据 = 在 ``STORES`` 里加一项，再在两张字表里各加三句话**（见下面「文字在哪」）。必须回答的只有
一个问题：硬盘没了，它从哪回来？

- ``git``：已经有机制把它放进某个私有仓库（写明哪个仓库、哪个机制）；
- ``rebuild``：能重新算出来或重新下载（缓存）；
- ``disposable``：丢了没有损失（锁、进程标记、日志、自愈的簿记）；
- ``secret`` / ``relogin``：密钥和登录态，各有各的恢复办法；
- ``uncovered``：该留却还只在本机。**必须**写明打算在路线图的哪一步补上。

人写的、AI 写的内容（``content``）和用户的设置（``settings``）只能是 ``git`` 或 ``uncovered``：
它们重算不出来，也不能说「丢了无所谓」。

这张表声明的是**设计**：某项标成 ``git`` 表示有机制能备份它，不表示用户此刻开着那个机制、也不表示上次备份
是什么时候。此刻的实际状态由配置全景的探针去看（``pet/panorama/storage_probe.py``）。

**文字在哪。** 表里只有标识和结构。给人看的话在字表里（``pet/locale/zh.json`` / ``en.json``），键按 ``text_key``：

- ``stores.<键>.name``：短名字（磁贴里列出来的那一行）；
- ``stores.<键>.holds``：一句话，里面是什么；
- ``stores.<键>.why``：为什么是这个恢复来源；``uncovered`` 时是为什么还没覆盖；
- ``stores.root.<根>``：这个根是哪里。

``tests/test_data_stores.py`` 查每一项在两张字表里这三句都在。
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass

#: 归哪个账号。``mixed`` = 个人和公司的内容混在同一个文件里：进任何仓库之前都得先分开（ADR 0003）。
ZONES = ("personal", "work", "mixed")
#: 位置的根。``data`` 是肥鱼自己的数据目录（%APPDATA%/big-fat-fish）；``home`` 是用户的家目录（只登记其中和 AI
#: 有关的文件）；``claude_home`` / ``claude_home_wsl`` 是个人的、WSL 里公司的 Claude Code 家目录（~/.claude）；
#: ``kb_personal`` / ``kb_work`` 是两个知识库的本地克隆；``keyring`` 是系统钥匙串；``os`` 是操作系统里的登记项。
ROOTS = ("data", "home", "claude_home", "claude_home_wsl", "kb_personal", "kb_work", "keyring", "os")
KINDS = ("settings", "content", "state", "cache", "log", "marker", "secret", "login")
RESTORE_SOURCES = ("git", "rebuild", "disposable", "secret", "relogin", "uncovered")
#: 可以进 ``git`` 的仓库：个人的进个人的，公司的进公司的（ADR 0003）。
REPOS = ("kb_personal", "kb_work")
#: 硬盘没了会怎样：``kept`` 有机制把它放进仓库；``local`` 该留却只在这台机器上；``free`` 丢了不要紧。
STANDINGS = ("kept", "local", "free")


@dataclass(frozen=True)
class Restore:
    """丢了从哪恢复。"""

    source: str
    repo: str = ""              # git：进了哪个仓库（REPOS 之一）
    via: str = ""               # git：靠哪个机制（模块名）
    plan: str = ""              # 还没做到的：打算在路线图哪一步补（如 "M6"）


@dataclass(frozen=True)
class Store:
    id: str
    zone: str                   # 归哪个账号带
    root: str                   # ROOTS 之一
    patterns: tuple[str, ...]   # 相对根的路径，正斜杠；* 可以跨目录
    kind: str                   # KINDS 之一
    writers: tuple[str, ...]    # 谁写它：模块名，或 "user" / "claude_code"
    restore: Restore
    code_names: tuple[str, ...] = ()    # 源码里拼这个文件名的写法，模式对不上时在这里补（只给守卫用）
    text: str = ""              # 文字用哪个键；空 = 用 id（两个 Claude Code 家目录共用一套话）


def text_key(store: Store) -> str:
    return store.text or store.id


def standing(store: Store) -> str:
    """硬盘没了，这一项会怎样（``STANDINGS`` 之一）。定了做法却还没做的（``plan`` 非空）算只在本机。"""
    source = store.restore.source
    if source == "uncovered" or (source == "secret" and store.restore.plan):
        return "local"
    return "kept" if source in ("git", "secret") else "free"


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
        if not store.patterns or not store.writers or not all(re.fullmatch(r"[a-z][a-z0-9_.]*", w) for w in store.writers):
            raise bad("patterns and writers (identifiers) are required")
        restore = store.restore
        if restore.source not in RESTORE_SOURCES:
            raise bad("unknown restore source")
        if restore.source == "git" and (restore.repo not in REPOS or not restore.via):
            raise bad("a git restore must name the repository and the mechanism")
        if restore.source == "uncovered" and not restore.plan:
            raise bad("an uncovered store must say which roadmap step closes the gap")
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
    return tuple(store for store in STORES if standing(store) == "local")


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


_DISPOSABLE = Restore("disposable")
_REBUILD = Restore("rebuild")
_GAP = Restore("uncovered", plan="M6")


def _claude_home(zone: str, root: str, suffix: str) -> tuple[Store, ...]:
    """一个 Claude Code 家目录里要登记的东西。个人的（Windows）和公司的（WSL）结构一样，各登记一遍，话共用一套。"""
    def store(name: str, patterns: tuple[str, ...], kind: str, writers: tuple[str, ...], restore: Restore) -> Store:
        return Store(name + suffix, zone, root, patterns, kind, writers, restore, text=name)

    return (
        store("claude_settings", ("settings.json", "settings.local.json", "keybindings.json"), "settings",
              ("claude_code", "user", "agent_link"), _GAP),
        store("claude_md", ("CLAUDE.md",), "content", ("user", "memory_distill"), _GAP),
        store("claude_memory", ("projects/*/memory/*.md",), "content", ("claude_code", "memory_distill"), _GAP),
        store("claude_skills", ("skills/*", "agents/*", "commands/*", "scripts/*", "plans/*"), "content",
              ("user", "claude_code"), _GAP),
        store("claude_plugins", ("plugins/installed_plugins.json", "plugins/*"), "cache", ("claude_code",), _REBUILD),
        store("claude_transcripts", ("projects/*/*.jsonl", "history.jsonl", "projects/*"), "log", ("claude_code",), _DISPOSABLE),
        store("claude_login", (".credentials.json",), "login", ("claude_code",), Restore("relogin")),
        store("claude_scratch",
              ("file-history/*", "shell-snapshots/*", "sessions/*", "cache/*", "backups/*", "paste-cache/*", "debug/*",
               "session-env/*", "ide/*", "downloads/*", "chrome/*", "daemon/*", "spares/*", "state/*", "*.bak", "*.bak2",
               ".last-*", "settings.json.before-*", "*.bak-*", "remote/*"), "state", ("claude_code",), _DISPOSABLE),
    )


#: ──────────────────────────────────────────────────────────────────────────────────────────────
#: 表。顺序只为好读：先是肥鱼的数据目录，再是肥鱼会去写或替用户照看的别处。每一项是什么、为什么是这个恢复来源，
#: 在字表的 ``stores.<id>.holds`` / ``.why`` 里。
#: ──────────────────────────────────────────────────────────────────────────────────────────────
STORES: tuple[Store, ...] = (
    # ── 设置 ──
    Store("config", "personal", "data", ("config.json",), "settings", ("config",),
          Restore("git", repo="kb_personal", via="config_backup")),
    Store("config_slots", "personal", "data", ("config-*.json",), "settings", ("config", "overlay_spawn_state"), _GAP),
    Store("config_local_copies", "personal", "data", ("config.json.bak", "config.json.corrupt-*", "config.json.before-*",
                                                      "config-*.json.bak", "config-*.json.corrupt-*"), "state",
          ("config", "slot_manager", "config_backup"), _DISPOSABLE),
    Store("config_backup_state", "personal", "data", ("config-backup-state.json",), "state", ("config_backup",), _DISPOSABLE),
    # ── 人和 AI 写下的内容 ──
    Store("distill_entries", "personal", "data", ("memory-distill/entries.json",), "content", ("memory_distill_sink",), _GAP),
    Store("distill_entries_work", "work", "data", ("memory-distill/entries-work.json",), "content", ("memory_distill_sink",), _GAP),
    Store("distill_proposals", "mixed", "data", ("memory-distill/proposals.json",), "content", ("memory_distill_run",), _GAP),
    Store("chat_sessions", "personal", "data", ("sessions/*.json", "sessions/*", "sessions-*/*.json", "sessions-*/*"), "content",
          ("chat.session_store",), _GAP),
    Store("todo_items", "personal", "data", ("todo_items.json", "todo_items-*.json"), "content", ("todo_reminder",), _GAP),
    Store("message_log", "personal", "data", ("message-log.json",), "content", ("message_log",), _GAP),
    Store("island_icons", "personal", "data", ("island-icons/*",), "content", ("settings_island_icon",), _GAP),
    Store("user_assets", "personal", "data", ("characters/*", "sounds/*"), "content", ("user",), _GAP),
    Store("session_history", "personal", "data", ("claude-session-history.json",), "state", ("claude_session_history",), _GAP),
    # ── 自愈的簿记 ──
    Store("distill_state", "mixed", "data", ("memory-distill/cursors.json", "memory-distill/distill-state*.json",
                                             "memory-distill/backups/*", "memory-distill/*"), "state",
          ("memory_distill", "memory_distill_run", "memory_distill_sink"), _DISPOSABLE),
    Store("distill_candidates", "mixed", "data", ("memory-distill/candidates/*.jsonl",), "cache", ("memory_distill",), _DISPOSABLE),
    Store("assistant_state", "personal", "data", ("personal-briefing.json", "activity.json", "file_eaten_stats.json",
                                                  "session-fish.json", "shuffle-state.json", "capture-organize.json",
                                                  "capture-review.json"), "state",
          ("personal_briefing", "activity_log", "file_eater", "session_fish_decisions", "shuffle_bag", "capture_organize",
           "capture_review"),
          _DISPOSABLE),
    Store("work_state", "work", "data", ("work-briefing.json", "slack-watch.json", "work-notes.json"), "state",
          ("work_briefing", "slack_watch", "work_notes"), _DISPOSABLE),
    # ── 缓存 ──
    Store("knowledge_base_copy", "personal", "data", ("knowledge-base/state.json", "knowledge-base/*"), "cache",
          ("chat.knowledge_base",), _REBUILD),
    Store("voice_cache", "personal", "data", ("voice_chime_cache/*", "self_talk_voice/*", "sounds_cache/*"), "cache",
          ("voice_chime_service", "self_talk_voice", "click_sound"), _REBUILD),
    Store("lyrics_cache", "personal", "data", ("lyrics_cache/*.json",), "cache", ("music_lyric",), _REBUILD),
    Store("probe_cache", "personal", "data", ("harness_probe_cache.json", "balance_cache.json"), "cache",
          ("harness_launcher", "app"), _REBUILD),
    Store("panorama_snapshot", "mixed", "data", ("panorama/*",), "cache", ("panorama",), _REBUILD),
    Store("panorama_session", "personal", "data", ("panorama-session.json", "panorama-session.json.tmp"), "state",
          ("panorama",), _DISPOSABLE),
    # ── 日志、锁和标记 ──
    Store("logs", "personal", "data", ("pet-*.log*", "pet-overlay-gate.log"), "log", ("app", "overlay_instance_gate"), _DISPOSABLE),
    Store("settings_audit", "mixed", "data", ("settings-audit.jsonl",), "log", ("settings_audit",), _DISPOSABLE),
    Store("run_journal", "mixed", "data", ("run-journal/*.jsonl",), "log", ("run_journal",), _DISPOSABLE),
    Store("agent_events", "mixed", "data", ("agent-events/*.jsonl", "agent-events/*"), "log", ("claude_code", "agent_link"),
          _DISPOSABLE),
    Store("runtime_markers", "personal", "data",
          ("overlay-instance.lock", "settings.lock", "overlay-active-pets.json", "overlay-settings-command.json",
           "migration-spawns.done", "agent-hooks-refresh.pending", "pet-runtime-*.json", "runtime-*.json", ".migration_staging/*"),
          "marker", ("overlay_instance_gate", "slot_manager", "overlay_spawn_state", "overlay_settings_command", "config"),
          _DISPOSABLE, code_names=("{}{}-slot-{}.json",)),
    # ── 肥鱼数据目录之外 ──
    *_claude_home("personal", "claude_home", ""),
    *_claude_home("work", "claude_home_wsl", "_wsl"),
    Store("claude_json", "personal", "home", (".claude.json",), "settings", ("claude_code",), _GAP),
    Store("kb_personal_repo", "personal", "kb_personal", ("*",), "content", ("user", "personal_vault", "capture_organize", "memory_distill"),
          Restore("git", repo="kb_personal", via="personal_vault")),
    Store("kb_work_repo", "work", "kb_work", ("*",), "content", ("work_notes", "slack_watch", "memory_distill"),
          Restore("git", repo="kb_work", via="work_notes")),
    # 定下的做法是加密后放个人私有仓库、主钥放密码管理器（ADR 0015）；还没实现，所以带着 plan
    Store("api_keys", "personal", "keyring", ("provider/*", "connector/*"), "secret", ("chat.models",),
          Restore("secret", plan="M6")),
    Store("autostart", "personal", "os", ("Run/*",), "state", ("autostart",), _REBUILD),
)

#: 源码里出现、长得像数据文件、但**不是**肥鱼落盘的数据：别家程序的文件、随包发的资源、文案键、临时目录里的东西。
#: 每条写一句它是什么。占位符写成 ``{}``（和守卫从 f-string 里读出来的样子一致）。
NOT_STORES: dict[str, str] = {
    "index.lock": "git 自己的索引锁（克隆的 .git 目录里）：同步器只看它在不在，在就不动这个克隆",
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
