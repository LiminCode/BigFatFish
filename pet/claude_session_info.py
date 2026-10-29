# -*- coding: utf-8 -*-
"""Claude Code 会话详情：最近的问题、在哪打开的、进程还在不在（纯逻辑 + 本机读取，零 Qt）。

会话小鱼平时只知道 hook 送来的几样东西（标题、项目名、工作目录、transcript 路径）。
用户点开详情 / 要跳转时，这里再去读两处 Claude Code 自己的文件：

- **transcript**（hook 给的 ``transcript_path``）尾部：``last-prompt`` 条目（最近一次
  提问）、``gitBranch``、``entrypoint``，以及最近一轮的 ``usage``（上下文用了多少）；
- **运行中会话清单** ``~/.claude/sessions/<pid>.json``：进程号、入口（``cli`` /
  ``claude-vscode`` / ``claude-desktop`` / ``sdk-cli``）、启动时间；桌面版起的还有
  ``hostSessionId``（桌面版那边的会话 id）。

这两处都是 Claude Code 的**内部格式**（官方文档明说 transcript 的条目格式会随版本变，
清单则完全没有文档），所以这里的每一步都按「读不到就留空」处理——调用方拿到的
``SessionDetail`` 永远可用，只是字段可能是空的。清单里还会留着进程早已不在的陈旧
文件，所以「还活着」必须拿进程号 + 进程启动时间去和系统核对。

**提问正文只在内存里**：按需读、读完交给界面，不写进事件文件、日志或配置
（``docs/AGENT_LINK_PROTOCOL.md`` §6）。

WSL 通道的两处文件在发行版里，经一次 ``wsl.exe`` 调用一并取回（``WSL_SCRIPT``）。
"""
from __future__ import annotations

import json
import re
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from . import claude_hooks

#: transcript 只读尾部这么多字节（最近一次提问、标题都在回合末尾反复追加）
TAIL_BYTES = 512 * 1024
#: 详情卡上「最近的问题」的显示上限
PROMPT_MAX = 300

ENTRY_VSCODE = "claude-vscode"
ENTRY_CLI = "cli"
ENTRY_DESKTOP = "claude-desktop"
#: 运行清单里 ``hostSessionId`` 的形状（Claude 桌面版 4.29 自己校验本地会话 id 用的就是它）
_HOST_SESSION_RE = re.compile(r"^local_[A-Za-z0-9-]{1,64}$")
#: 入口 → 给人看的说法的文案键（不认识的原样显示；显示时 t()，跟界面语言）
ENTRY_TEXT = {ENTRY_VSCODE: "session_info.ui.entry_vscode", ENTRY_CLI: "session_info.ui.entry_cli",
              "sdk-cli": "session_info.ui.entry_sdk", ENTRY_DESKTOP: "session_info.ui.entry_desktop"}

#: 从哪开的 → 图标种类（``host_icons`` 用它取那个程序自己的图标）


def host_kind(entrypoint: str, wsl: bool) -> str:
    """``vscode`` / ``desktop``（Claude 桌面版）/ ``terminal``（本机终端）/ ``wsl``（WSL 终端）/
    ``script`` / 空（认不出）。WSL 里的 VS Code 仍是 VS Code。"""
    if entrypoint == ENTRY_VSCODE:
        return "vscode"
    if entrypoint == ENTRY_DESKTOP:
        return "desktop"
    if entrypoint == "sdk-cli":
        return "script"
    if wsl:
        return "wsl"
    return "terminal" if entrypoint == ENTRY_CLI else ""


#: Windows FILETIME（1601 起、100ns）→ Unix 秒
_FILETIME_EPOCH_S = 11644473600


@dataclass
class SessionDetail:
    """一个会话的全部已知信息。``alive``：True / False / None（无从判断）。"""

    agent: str = "claude"
    session_id: str = ""
    title: str = ""
    project: str = ""
    cwd: str = ""
    transcript: str = ""
    phase: str = ""
    tool: str = ""
    last_prompt: str = ""
    git_branch: str = ""
    entrypoint: str = ""
    version: str = ""
    name: str = ""
    pid: int | None = None
    started_at: float | None = None    # Unix 秒
    alive: bool | None = None
    distro: str = ""                   # WSL 发行版名（仅 WSL 通道）
    model: str = ""                    # 最近一轮实际用的模型 id（会话记录 assistant.message.model）
    effort: str = ""                   # 最近一轮的 effort（perTurnEffort，没有就会话级的 effort）
    context_tokens: int = 0            # 最近一轮送进模型的上下文有多少 token（0 = 不知道）
    extra: dict = field(default_factory=dict)

    @property
    def is_wsl(self) -> bool:
        return self.agent == "claude_wsl"

    @property
    def entry_text(self) -> str:
        from .i18n import t

        where = t(ENTRY_TEXT[self.entrypoint]) if self.entrypoint in ENTRY_TEXT else self.entrypoint
        if self.is_wsl:
            return f"{where} · WSL" if where else "WSL"
        return where

    @property
    def host(self) -> str:
        """从哪开的（图标种类，见 ``host_kind``）。"""
        return host_kind(self.entrypoint, self.is_wsl)

    @property
    def resume_command(self) -> str:
        """在终端里重新打开这个会话的命令（官方文档：按 ID 恢复不要求同一目录）。"""
        return f"claude --resume {self.session_id}" if self.session_id else ""


def from_session(agent: str, info: dict) -> SessionDetail:
    """用 hook 送来的那几样（``SessionPetController.sessions()`` 的一项）起一份详情。"""
    return SessionDetail(
        agent=str(agent or "claude"), session_id=str(info.get("sessionId") or ""),
        title=str(info.get("title") or ""), project=str(info.get("project") or ""),
        cwd=str(info.get("cwd") or ""), transcript=str(info.get("transcript") or ""),
        phase=str(info.get("phase") or ""), tool=str(info.get("tool") or ""))


# ---------------------------------------------------------------- 解析
def parse_transcript_tail(text: str) -> dict:
    """从 transcript 尾部取 ``last_prompt / title / git_branch / entrypoint / version / cwd``，
    以及 ``model / effort / context_tokens``。

    逐行当 JSON 解析，从后往前、每个字段取最靠后的一次出现；解析不了的行（被截断的
    第一行、格式变了的行）直接跳过。
    """
    found: dict[str, str] = {}
    # custom_title 也在必须找齐的名单里：没改过名的会话永远找不到它，于是整段尾部都会
    # 扫完——这是有意的，否则找齐其它字段提前收工时，可能还没扫到更靠前的那条改名记录。
    wanted = {"last_prompt", "title", "custom_title", "git_branch", "entrypoint", "version", "cwd",
              "model", "effort", "context_tokens"}
    for line in reversed(text.splitlines()):
        if not line.startswith("{"):
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        kind = entry.get("type")
        if kind == "last-prompt":
            found.setdefault("last_prompt", _clean(entry.get("lastPrompt"), PROMPT_MAX))
        elif kind == "ai-title":
            found.setdefault("title", _clean(entry.get("aiTitle"), 80))
        elif kind == "custom-title":
            # 用户在 Claude Code 里给会话改的名字。改名后 ai-title 照样继续追加，
            # 所以它单独记，最后盖过自动标题。
            found.setdefault("custom_title", _clean(entry.get("customTitle"), 80))
        elif kind == "assistant" and not entry.get("isSidechain"):
            # 主对话最近一轮用的模型与 effort（子代理的记录 isSidechain 为真，不算）
            message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
            found.setdefault("model", _clean(message.get("model") or entry.get("requestedModel"), 60))
            found.setdefault("effort", _clean(entry.get("perTurnEffort") or entry.get("effort"), 20))
            used = context_used(message.get("usage"))
            if used:
                found.setdefault("context_tokens", used)
        elif kind == "system" and entry.get("subtype") == "compact_boundary":
            # 压缩之后、下一轮回复之前：上下文就是压缩后剩下的那些
            meta = entry.get("compactMetadata") if isinstance(entry.get("compactMetadata"), dict) else {}
            if isinstance(meta.get("postTokens"), int) and meta["postTokens"] > 0:
                found.setdefault("context_tokens", meta["postTokens"])
        for key, source in (("git_branch", "gitBranch"), ("entrypoint", "entrypoint"),
                            ("version", "version"), ("cwd", "cwd")):
            value = entry.get(source)
            if isinstance(value, str) and value:
                found.setdefault(key, value)
        if wanted <= found.keys():
            break
    if found.get("custom_title"):
        found["title"] = found["custom_title"]      # 调用方只认 title：用户改的名字优先
    return {key: value for key, value in found.items() if value}


def context_used(usage) -> int:
    """一轮回复的 ``usage`` → 这一轮送进模型的上下文总量（没缓存的 + 写缓存的 + 读缓存的）。"""
    if not isinstance(usage, dict):
        return 0
    total = 0
    for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        value = usage.get(key)
        if isinstance(value, int) and value > 0:
            total += value
    return total


#: 上下文窗口：这几代模型都是 1M（Claude API 文档的模型表，2026-10）；更早的 Claude 是 200K，
#: 其中 Sonnet 4 / 4.5 开了 1M 测试版时模型名后面带 ``[1m]``。
_WINDOW_1M_RE = re.compile(r"^claude-(?:(?:fable|mythos|sonnet|haiku|opus)-[5-9]|opus-4-[6-9]|sonnet-4-[6-9])(?:-|$)")
_CLAUDE_RE = re.compile(r"^claude-")


def context_window(model_id: str) -> int:
    """模型的上下文窗口（token）；认不出的模型返回 0（界面就只写用了多少，不画比例）。"""
    text = str(model_id or "").strip().lower()
    if text.endswith("[1m]") or _WINDOW_1M_RE.match(text):
        return 1_000_000
    return 200_000 if _CLAUDE_RE.match(text) else 0


_MODEL_ID_RE = re.compile(r"^claude-(?P<name>[a-z]+)-(?P<major>\d+)-(?P<minor>\d+)(?:-|$)")


def model_label(model_id: str) -> str:
    """``claude-fable-5-1`` → ``Fable 5.1``；认不出的原样给。"""
    text = str(model_id or "")
    match = _MODEL_ID_RE.match(text)
    if not match:
        return text
    return f"{match.group('name').capitalize()} {match.group('major')}.{match.group('minor')}"


def _clean(value, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def parse_registry(texts: Iterable[str]) -> dict[str, dict]:
    """清单文件内容 → ``{sessionId: 条目}``；同一会话有多条时取最近更新的。"""
    result: dict[str, dict] = {}
    for text in texts:
        try:
            entry = json.loads(text)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        sid = str(entry.get("sessionId") or "")
        if not sid or not isinstance(entry.get("pid"), int):
            continue
        known = result.get(sid)
        if known is None or _number(entry.get("updatedAt")) >= _number(known.get("updatedAt")):
            result[sid] = entry
    return result


def _number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def apply_registry(detail: SessionDetail, entry: dict | None) -> None:
    if not entry:
        return
    detail.pid = entry.get("pid") if isinstance(entry.get("pid"), int) else None
    detail.entrypoint = str(entry.get("entrypoint") or detail.entrypoint)
    detail.name = str(entry.get("name") or "")
    if entry.get("nameSource") == "user" and detail.name:
        # 运行清单里的 name 多数是自动拼的（项目名-两位十六进制）；只有 nameSource 是
        # user 的才是用户起的名字，这时它就是会话的标题。
        detail.title = _clean(detail.name, 80)
        detail.extra["title_by_user"] = True
    detail.version = str(entry.get("version") or detail.version)
    started = _number(entry.get("startedAt"))
    detail.started_at = started / 1000.0 if started else None
    # 进程启动时所在的目录。会话中途 cd 走了之后 detail.cwd 跟着变，这个不变——
    # VS Code 插件把进程起在工作区的第一个文件夹里，跳转时靠它分辨窗口。
    detail.extra["start_cwd"] = str(entry.get("cwd") or "")
    # Claude 桌面版起的会话：桌面版那边的会话 id（跳转时打开 claude://claude.ai/epitaxy/<id>）
    host = str(entry.get("hostSessionId") or "")
    if _HOST_SESSION_RE.match(host):
        detail.extra["host_session"] = host
    if not detail.cwd:
        detail.cwd = str(entry.get("cwd") or "")


def apply_transcript(detail: SessionDetail, parsed: dict) -> None:
    detail.last_prompt = parsed.get("last_prompt", "")
    detail.git_branch = parsed.get("git_branch", "")
    detail.model = parsed.get("model", "")
    detail.effort = parsed.get("effort", "")
    detail.context_tokens = int(parsed.get("context_tokens") or 0)
    detail.entrypoint = detail.entrypoint or parsed.get("entrypoint", "")
    detail.version = detail.version or parsed.get("version", "")
    if parsed.get("custom_title"):
        detail.title = parsed["custom_title"]          # 用户改的名字盖过 hook 报上来的自动标题
    elif not detail.extra.get("title_by_user"):
        detail.title = detail.title or parsed.get("title", "")
    detail.cwd = detail.cwd or parsed.get("cwd", "")


# ---------------------------------------------------------------- 本机（Windows / 原生）读取
def read_tail(path: Path | str, limit: int = TAIL_BYTES) -> str:
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - limit))
            return handle.read().decode("utf-8", "replace")
    except OSError:
        return ""


def find_transcript(session_id: str, home: Path | None = None) -> str:
    """按会话 ID 找 transcript（``~/.claude/projects/<项目>/<id>.jsonl``）。

    hook 只在回合边界送路径；肥鱼刚启动、会话还在回合中途时路径还没到，先这样找。
    """
    if not _safe_session_id(session_id):
        return ""
    projects = (home or Path.home()) / ".claude" / "projects"
    try:
        return next((str(p) for p in projects.glob(f"*/{session_id}.jsonl")), "")
    except OSError:
        return ""


def registry_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".claude" / "sessions"


def read_registry(directory: Path) -> dict[str, dict]:
    texts = []
    try:
        files = sorted(directory.glob("*.json"))
    except OSError:
        files = []
    for path in files:
        try:
            texts.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return parse_registry(texts)


def process_alive(entry: dict) -> bool | None:
    """清单条目指的那个进程还在不在（进程号 + 启动时间都对得上才算）。

    只核对本机进程；psutil 不可用时返回 None（无从判断，调用方按「不知道」处理，
    不据此让小鱼离场）。
    """
    pid = entry.get("pid")
    if not isinstance(pid, int):
        return None
    try:
        import psutil
    except ImportError:
        return None
    try:
        process = psutil.Process(pid)
        created = process.create_time()
    except psutil.NoSuchProcess:
        return False
    except psutil.Error:
        return None
    expected = _proc_start_seconds(entry.get("procStart"))
    if expected is None:
        return True
    return abs(created - expected) < 5.0      # 进程号被别的进程复用了 → 不是它


def _proc_start_seconds(raw) -> float | None:
    """清单里的 ``procStart``（Windows：FILETIME 字符串）→ Unix 秒；别的平台不比对。"""
    if sys.platform != "win32":
        return None
    try:
        return int(str(raw)) / 1e7 - _FILETIME_EPOCH_S
    except (TypeError, ValueError):
        return None


def load_local(detail: SessionDetail, *, home: Path | None = None,
               alive: Callable[[dict], bool | None] = process_alive) -> SessionDetail:
    """补全一个本机（非 WSL）会话的详情；返回同一个对象。"""
    entry = read_registry(registry_dir(home)).get(detail.session_id)
    apply_registry(detail, entry)
    if entry is not None:
        detail.alive = alive(entry)
    if not detail.transcript:
        detail.transcript = find_transcript(detail.session_id, home)
    if detail.transcript:
        apply_transcript(detail, parse_transcript_tail(read_tail(detail.transcript)))
    return detail


def local_liveness(session_ids: Iterable[str], *, home: Path | None = None,
                   alive: Callable[[dict], bool | None] = process_alive) -> dict[str, bool | None]:
    """一批本机会话是否还活着：``{sessionId: True / False / None}``。

    清单里没有这条会话 = None（清单是内部文件，没有记录不等于会话没了）。
    """
    registry = read_registry(registry_dir(home))
    result: dict[str, bool | None] = {}
    for sid in session_ids:
        entry = registry.get(sid)
        result[sid] = alive(entry) if entry is not None else None
    return result


# ---------------------------------------------------------------- WSL 读取
#: 在发行版里跑的脚本：发行版名、清单文件（附该进程此刻的启动时刻，对不上 = 已死）、
#: ``$2`` 那个会话的进程是在哪种终端里跑的（两个环境变量），以及 ``$1`` 指的
#: transcript 尾部。各段用 ``@@`` 开头的标记行分隔。
WSL_SCRIPT = r'''
echo "@@distro ${WSL_DISTRO_NAME:-}"
for f in "$HOME"/.claude/sessions/*.json; do
    [ -f "$f" ] || continue
    p=${f##*/}; p=${p%.json}
    s=
    [ -r "/proc/$p/stat" ] && s=$(sed 's/^.*) //' "/proc/$p/stat" 2>/dev/null | cut -d" " -f20)
    printf '@@reg %s ' "$s"; tr -d '\n' < "$f"; echo
    if [ -n "${2:-}" ] && [ -r "/proc/$p/environ" ] && grep -q "\"sessionId\":\"$2\"" "$f" 2>/dev/null; then
        tr '\0' '\n' < "/proc/$p/environ" 2>/dev/null | grep -E '^(TERM_PROGRAM|WT_SESSION)=' | sed 's/^/@@env /'
    fi
done
t=${1:-}
# hook 只在回合边界送 transcript 路径：还没送到时按会话 ID 找
[ -z "$t" ] && [ -n "${2:-}" ] && t=$(ls "$HOME"/.claude/projects/*/"$2".jsonl 2>/dev/null | head -n 1)
echo "@@tail"
[ -n "$t" ] && tail -c ''' + str(TAIL_BYTES) + r''' "$t" 2>/dev/null
:
'''


def parse_wsl_output(text: str) -> dict:
    """``WSL_SCRIPT`` 的输出 → ``{"distro", "registry", "alive", "env", "tail"}``。

    ``alive``：``{sessionId: 是否活着}``；``env``：被问的那个会话进程的
    ``TERM_PROGRAM`` / ``WT_SESSION``（跳转时用来判断它在哪种终端里）。
    """
    head, found, tail = text.partition("\n@@tail\n")
    if not found:
        head, tail = text, ""
    distro = ""
    entries: list[str] = []
    live_start: dict[int, str] = {}
    env: dict[str, str] = {}
    for line in head.splitlines():
        if line.startswith("@@distro "):
            distro = line[len("@@distro "):].strip()
        elif line.startswith("@@env "):
            key, _sep, value = line[len("@@env "):].partition("=")
            env[key] = value
        elif line.startswith("@@reg "):
            start, _sep, body = line[len("@@reg "):].partition(" ")
            if not body.startswith("{"):       # 进程不在：启动时刻那一栏是空的
                body, start = (start + " " + body).strip(), ""
            entries.append(body)
            try:
                pid = json.loads(body).get("pid")
            except (ValueError, AttributeError):
                continue
            if isinstance(pid, int):
                live_start[pid] = start
    registry = parse_registry(entries)
    alive = {}
    for sid, entry in registry.items():
        now = live_start.get(entry["pid"], "")
        recorded = str(entry.get("procStart") or "")
        # 进程在，且启动时刻对得上（清单没记启动时刻就只看进程在不在）
        alive[sid] = bool(now) and (not recorded or now == recorded)
    return {"distro": distro, "registry": registry, "alive": alive, "env": env, "tail": tail}


def _safe_session_id(session_id: str) -> str:
    """会话 ID 要拼进发行版里的 grep 模式：只放行 UUID 用得到的字符。"""
    return session_id if session_id and all(c.isalnum() or c == "-" for c in session_id) else ""


def load_wsl(detail: SessionDetail, *, runner=claude_hooks.run_wsl) -> SessionDetail:
    """补全一个 WSL 会话的详情（一次 wsl.exe 调用；失败则原样返回）。"""
    code, out = runner(["-e", "sh", "-c", WSL_SCRIPT, "sh", detail.transcript,
                        _safe_session_id(detail.session_id)])
    if code != 0 and not out:
        return detail
    parsed = parse_wsl_output(out)
    detail.distro = parsed["distro"]
    entry = parsed["registry"].get(detail.session_id)
    apply_registry(detail, entry)
    if entry is not None:
        detail.alive = parsed["alive"].get(detail.session_id)
    detail.extra["env"] = parsed["env"]
    apply_transcript(detail, parse_transcript_tail(parsed["tail"]))
    return detail


def wsl_liveness(session_ids: Iterable[str], *,
                 runner=claude_hooks.run_wsl) -> dict[str, bool | None]:
    code, out = runner(["-e", "sh", "-c", WSL_SCRIPT, "sh", ""])
    if code != 0 and not out:
        return {sid: None for sid in session_ids}
    parsed = parse_wsl_output(out)
    return {sid: (parsed["alive"].get(sid) if sid in parsed["registry"] else None)
            for sid in session_ids}


def load(detail: SessionDetail) -> SessionDetail:
    """按通道补全详情（阻塞：读文件 / 起 wsl.exe——在后台线程里调）。"""
    try:
        return load_wsl(detail) if detail.is_wsl else load_local(detail)
    except Exception:
        return detail      # 内部格式随时可能变：详情是锦上添花，绝不因此出错
