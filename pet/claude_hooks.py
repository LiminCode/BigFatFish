# -*- coding: utf-8 -*-
"""Claude Code hooks 接入的纯逻辑层（零 Qt）。

``pet/agent_link.py`` 的 ``ClaudeCodeMonitor`` 只做 Qt 侧接线，下面四件事都在这里：

1. **hook 脚本**（``hook_script_text``）：POSIX sh，由 hook 命令 ``source`` 执行，
   只用 shell 内建命令。旧脚本每个事件都要起一次 PowerShell（实测中位数 284ms，
   Claude Code 同步等它跑完）；本脚本在 Git Bash 下比空壳多约 10ms、WSL 下约 4ms
   （2026-10-10 实测，n=10/100）。只读 stdin 前 4096 字节——``session_id`` /
   ``tool_name`` / ``notification_type`` 都排在载荷最前面，而 ``PostToolUse`` 的
   ``tool_response`` 可以有几百 KB（shell 的 ``read`` 逐字节读，300KB 实测 600ms）。
2. **settings.json 合并**（``merge_hooks`` / ``strip_hooks``）：只动带
   ``x-dsh-pet`` 标记的条目，用户自己的 hooks 原样保留。
3. **WSL 通道**（``WslSettingsStore`` / ``to_wsl_path``）：桌宠跑在 Windows，
   Claude Code 跑在 WSL 发行版里——读写发行版内的 ``~/.claude/settings.json``
   一律经 ``wsl.exe``，事件文件仍落在 Windows 侧（WSL 里看是 ``/mnt/c/…``）。
4. **会话收敛**（``ClaudeSessionTracker``）：同一个 Claude Code 可以同时开多个
   会话，全部写同一个事件文件。按 ``sessionId`` 分别记账，再收敛成一个 Agent 级
   状态——否则一个会话收工会被当成「全都干完了」。

隐私口径（docs/AGENT_LINK_PROTOCOL.md §6）：脚本只落时间戳 / 事件名 / 会话 ID /
工具名 / 通知类型；提问、代码、命令、路径一律不写。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

#: 注入的 hook 事件。Stop / StopFailure 是回合边界；Notification 用来感知
#: 「在等用户批准」；SessionEnd 让关掉的会话不再占着「忙」。
HOOK_EVENTS = (
    "PreToolUse", "PostToolUse", "PostToolUseFailure", "Stop", "StopFailure",
    "SessionStart", "SessionEnd", "UserPromptSubmit", "Notification",
)
HOOK_FLAG = "x-dsh-pet"            # 本桌宠注入条目的结构化标记
HOOK_SCRIPT_NAME = "claude_event_hook.sh"
#: 无标记旧条目的兜底识别（早期版本注入）：命令里带这些脚本文件名才算我们的。
_LEGACY_SCRIPT_MARKERS = ("claude_event_hook.ps1", "claude_event_hook.py", HOOK_SCRIPT_NAME)

_HOOK_SCRIPT = r"""# dsh-pet: Claude Code 事件 hook。由桌宠生成、每次启动刷新，请勿手改。
# 由 hook 命令 source 执行；事件名 / Agent 名 / 输出文件经环境变量传入。
# 只落元数据（时间戳、事件名、会话 ID、工具名、通知类型），其余一概不写。
if [ -n "${BASH_VERSION:-}" ]; then
    IFS= read -r -n 4096 _dp_in || :
else
    _dp_in=$(head -c 4096)
fi
_dp_pick() {
    case $_dp_in in
        *"\"$1\":\""*) _dp_v=${_dp_in#*"\"$1\":\""}; _dp_v=${_dp_v%%\"*} ;;
        *) _dp_v= ;;
    esac
    case $_dp_v in *[!A-Za-z0-9_.:-]*) _dp_v= ;; esac
}
_dp_raw() {
    case $_dp_in in
        *"\"$1\":\""*) _dp_v=${_dp_in#*"\"$1\":\""}; _dp_v=${_dp_v%%\"*} ;;
        *) _dp_v= ;;
    esac
}
_dp_pick session_id
_dp_sid=$_dp_v
_dp_rec="\"sessionId\":\"$_dp_sid\""
case ${DSH_PET_EVENT:-} in
    PreToolUse|PostToolUse|PostToolUseFailure)
        _dp_pick tool_name
        [ -z "$_dp_v" ] || _dp_rec="$_dp_rec,\"tool\":\"$_dp_v\"" ;;
    Notification)
        _dp_pick notification_type
        [ -z "$_dp_v" ] || _dp_rec="$_dp_rec,\"ntype\":\"$_dp_v\"" ;;
esac
_dp_ts=${EPOCHREALTIME:-}
[ -n "$_dp_ts" ] || _dp_ts=$(date +%s)
case $_dp_ts in *,*) _dp_ts="${_dp_ts%,*}.${_dp_ts#*,}" ;; esac
{ printf '{"ts":%s,"agent":"%s","event":"%s",%s}\n' \
    "$_dp_ts" "${DSH_PET_AGENT:-claude}" "${DSH_PET_EVENT:-unknown}" "$_dp_rec" >> "$DSH_PET_OUT"; } 2>/dev/null || :
# 回合边界（每回合两次）再补一行会话标签：项目文件夹名 + transcript 里最后一个
# ai-title。单独成行——值是原样截出来的 JSON 字符串片段，万一拼坏只丢这一行，
# 不连累上面的事件行。截到第一个反斜杠为止，所以片段里不会剩转义序列。
case ${DSH_PET_EVENT:-} in
    UserPromptSubmit|Stop)
        _dp_raw cwd
        _dp_proj=${_dp_v##*/}; _dp_proj=${_dp_proj##*\\}
        _dp_raw transcript_path
        _dp_path=$_dp_v; _dp_title=
        if [ -n "$_dp_path" ]; then
            # Windows 路径在 JSON 里是 C:\\Users\\…：还原成单反斜杠（bash 专有语法放进 eval，dash 不解析）
            [ -z "${BASH_VERSION:-}" ] || eval '_dp_path=${_dp_path//\\\\/\\}'
            _dp_tail=$(tail -c 131072 "$_dp_path" 2>/dev/null)
            case $_dp_tail in
                *'"aiTitle":"'*)
                    _dp_title=${_dp_tail##*\"aiTitle\":\"}
                    _dp_title=${_dp_title%%\"*}; _dp_title=${_dp_title%%\\*} ;;
            esac
        fi
        { printf '{"agent":"%s","event":"SessionMeta","sessionId":"%s","project":"%s","title":"%s"}\n' \
            "${DSH_PET_AGENT:-claude}" "$_dp_sid" "$_dp_proj" "$_dp_title" >> "$DSH_PET_OUT"; } 2>/dev/null || : ;;
esac
"""

# Windows 上没有 Git Bash 时的回退（Claude Code 这时用 PowerShell 跑 hook）。
# 慢（每事件起一次 PowerShell），但字段与 sh 脚本对齐。
_PS_HOOK_SCRIPT = (
    "param([string]$EventName = 'unknown', [string]$Agent = 'claude')\n"
    "$tool = ''; $sid = ''; $ntype = ''\n"
    "if ([Console]::IsInputRedirected) {\n"
    "  try {\n"
    "    $raw = [Console]::In.ReadToEnd()\n"
    "    if ($raw) {\n"
    "      $j = $raw | ConvertFrom-Json -ErrorAction Stop\n"
    "      if ($j.tool_name) { $tool = [string]$j.tool_name }\n"
    "      if ($j.session_id) { $sid = [string]$j.session_id }\n"
    "      if ($j.notification_type) { $ntype = [string]$j.notification_type }\n"
    "    }\n"
    "  } catch {}\n"
    "}\n"
    "$file = Join-Path $PSScriptRoot ($Agent + '.jsonl')\n"
    "$rec = [ordered]@{ ts = [DateTimeOffset]::Now.ToUnixTimeMilliseconds() / 1000.0; agent = $Agent; event = $EventName; sessionId = $sid }\n"
    "if ($tool) { $rec['tool'] = $tool }\n"
    "if ($ntype) { $rec['ntype'] = $ntype }\n"
    "# ConvertTo-Json 负责全部转义，不手工拼 JSON\n"
    "Add-Content -Path $file -Value ($rec | ConvertTo-Json -Compress) -Encoding UTF8\n"
)


def hook_script_text() -> str:
    """sh hook 脚本正文（LF 行尾；与输出路径无关，两个通道共用同一份）。"""
    return _HOOK_SCRIPT


def ps_hook_script_text() -> str:
    return _PS_HOOK_SCRIPT


def write_hook_script(path: Path) -> None:
    """落地 sh 脚本。必须按字节写：``write_text`` 在 Windows 上会把 LF 换成 CRLF，
    而 dash 把行尾的 ``\\r`` 当成命令的一部分。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_HOOK_SCRIPT.encode("utf-8"))


def _sq(value: str) -> str:
    """sh 单引号字面量（路径里出现 ``$`` / 空格 / 反引号都安全）。"""
    return "'" + str(value).replace("'", "'\\''") + "'"


def sh_hook_command(script: str, out: str, agent: str, event: str) -> str:
    """hook 命令：脚本存在才 source，且永远以 0 退出。

    脚本缺失时（桌宠卸载了但 hooks 还在）直接 ``.`` 一个不存在的文件会让非交互
    shell 报错退出，Claude Code 每个事件都要记一条 hook 失败——所以先 ``[ -r ]``。
    """
    return (
        f"f={_sq(script)}; [ -r \"$f\" ] && DSH_PET_EVENT={event} DSH_PET_AGENT={agent} "
        f"DSH_PET_OUT={_sq(out)} . \"$f\"; :"
    )


def ps_hook_command(script: str, agent: str, event: str) -> str:
    return f'powershell -NoProfile -ExecutionPolicy Bypass -File "{script}" {event} {agent}'


def hook_entry(command: str, shell: str | None = None) -> dict:
    """一条 matcher 组（Claude Code 要求的「数组对象」格式）。"""
    hook: dict[str, Any] = {"type": "command", "command": command}
    if shell:
        hook["shell"] = shell      # 仅 Windows 有意义：显式钉住执行 hook 的 shell
    return {"matcher": "", "hooks": [hook], HOOK_FLAG: True}


def find_git_bash() -> str | None:
    """Windows 上 Claude Code 默认拿来跑 hook 的 Git Bash；找不到返回 None。"""
    if sys.platform != "win32":
        return None
    candidates: list[Path] = []
    configured = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if configured:
        candidates.append(Path(configured))
    git = shutil.which("git")
    if git:
        # git.exe 可能在 <Git>/cmd、<Git>/bin 或 <Git>/mingw64/bin 下
        for root in list(Path(git).resolve().parents)[:3]:
            candidates.append(root / "bin" / "bash.exe")
    for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            sub = Path(base) / "Programs" if var == "LOCALAPPDATA" else Path(base)
            candidates.append(sub / "Git" / "bin" / "bash.exe")
    for path in candidates:
        try:
            if path.is_file():
                return str(path)
        except OSError:
            continue
    return None


# ---------------------------------------------------------------- settings.json 合并

def is_our_entry(entry: Any) -> bool:
    """是不是本桌宠注入的 matcher 组（新格式认标记，旧格式认脚本文件名）。"""
    if not isinstance(entry, dict):
        return False
    if entry.get(HOOK_FLAG) is True:
        return True
    for hook in entry.get("hooks") or []:
        command = str(hook.get("command", "")) if isinstance(hook, dict) else ""
        if any(marker in command for marker in _LEGACY_SCRIPT_MARKERS):
            return True
    return False


def strip_hooks(data: dict) -> dict:
    """移除本桌宠的全部条目（就地改并返回）；清空的事件键一并删掉。"""
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return data
    for name in list(hooks.keys()):
        entries = hooks.get(name)
        if not isinstance(entries, list):
            continue
        kept = [group for group in entries if not is_our_entry(group)]
        if kept:
            hooks[name] = kept
        else:
            del hooks[name]
    return data


def merge_hooks(data: dict, entries: dict[str, dict]) -> dict:
    """把 ``{事件名: matcher 组}`` 并入 settings（就地改并返回），幂等。

    先清掉我们以前注入的**所有**事件上的条目（含旧版本注入、现已不再使用的事件），
    再逐事件追加——升级后不会留下指向旧脚本的孤儿条目。
    """
    strip_hooks(data)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        data["hooks"] = hooks
    for name, entry in entries.items():
        existing = hooks.get(name)
        if not isinstance(existing, list):
            existing = []
        existing.append(entry)
        hooks[name] = existing
    return data


# ---------------------------------------------------------------- WSL 通道

_NO_WINDOW = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
_WSL_TIMEOUT_S = 30.0   # 发行版冷启动要几秒；调用方一律在后台线程
_MISSING = "__DSH_PET_NO_SETTINGS__"

WslRunner = Callable[..., "tuple[int, str]"]


def wsl_exe() -> str | None:
    if sys.platform != "win32":
        return None
    return shutil.which("wsl.exe")


def run_wsl(args: list[str], *, input_text: str | None = None,
            timeout: float = _WSL_TIMEOUT_S) -> tuple[int, str]:
    """在默认发行版里跑一条命令，返回 (返回码, stdout)。任何失败都折成非零返回码。

    ``CREATE_NO_WINDOW``：桌宠由 pythonw / GUI exe 启动时没有控制台，不带它每次调用
    都会闪一个终端窗口。``WSL_UTF8=1``：否则 wsl.exe 自己的输出是 UTF-16。
    """
    exe = wsl_exe()
    if not exe:
        return 127, ""
    try:
        proc = subprocess.run(
            [exe, *args],
            input=None if input_text is None else input_text.encode("utf-8"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=dict(os.environ, WSL_UTF8="1"),
            creationflags=_NO_WINDOW, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def to_wsl_path(win_path: Path | str, *, runner: WslRunner = run_wsl) -> str | None:
    """Windows 路径 → 默认发行版里的路径（``wslpath -a``，尊重自定义 automount 根）。"""
    code, out = runner(["-e", "wslpath", "-a", str(win_path)])
    path = out.strip()
    return path if code == 0 and path.startswith("/") else None


class WslSettingsStore:
    """默认发行版里 ``~/.claude/settings.json`` 的读写（全部经 wsl.exe）。

    不走 ``\\\\wsl.localhost`` 共享：经共享 ``os.replace`` 出来的文件权限会被重置成
    644（实测 600 → 644），而 settings.json 的 ``env`` 里可能放着密钥。这里在发行版
    内写临时文件、照抄原文件权限再 ``mv``——原子替换，权限不变。
    """

    _READ = ('f="$HOME/.claude/settings.json"; '
             f'[ -f "$f" ] || {{ printf %s {_MISSING}; exit 0; }}; cat "$f"')
    _WRITE = ('d="$HOME/.claude"; f="$d/settings.json"; t="$f.dsh-pet.tmp"; '
              'mkdir -p "$d" && umask 077 && cat > "$t" && '
              '{ [ ! -e "$f" ] || chmod "$(stat -c %a "$f")" "$t"; } && mv -f "$t" "$f"')

    def __init__(self, runner: WslRunner = run_wsl) -> None:
        self._run = runner

    def read(self) -> str | None:
        """文件内容；文件不存在返回 ``""``；**读失败返回 None**（调用方必须中止，
        绝不能拿空配置覆盖用户的 settings.json）。"""
        code, out = self._run(["-e", "sh", "-c", self._READ])
        if code != 0:
            return None
        return "" if out.strip() == _MISSING else out

    def write(self, text: str) -> bool:
        code, _out = self._run(["-e", "sh", "-c", self._WRITE], input_text=text)
        return code == 0


# ---------------------------------------------------------------- 会话呈现文案

#: 逐会话阶段 → 标签上的状态文案（会话小鱼与灵动岛卡片共用）
PHASE_TEXT = {"working": "工作中", "waiting": "等你批准", "resting": "休息中"}
_PHASE_COUNT_TEXT = {"waiting": "{n} 个等你批准", "working": "{n} 个在干活", "resting": "{n} 个休息中"}
#: 汇总时的排序：最需要人管的排最前
_PHASE_ORDER = ("waiting", "working", "resting")
#: 灵动岛胶囊上的计数：(阶段, 短标签)，按显示顺序
_CAPSULE_PHASES = (("working", "工作中"), ("resting", "休息中"), ("waiting", "等待中"))
#: 两个通道可能开着同名项目：WSL 那边的加个后缀区分
CHANNEL_SUFFIX = {"claude_wsl": " (WSL)"}


def session_label(agent: str, info: dict) -> str:
    """一个会话的显示名：标题 > 项目文件夹名 > 会话 ID 前 8 位。"""
    name = str(info.get("title") or info.get("project") or str(info.get("sessionId") or "")[:8]
               or "Claude Code")
    return f"{name}{CHANNEL_SUFFIX.get(str(agent), '')}"


def session_counts(sessions: list[dict]) -> list[tuple[str, str]]:
    """在用的会话按阶段计数：``[("working", "2 工作中"), ...]``；没有的阶段不出现。

    灵动岛胶囊用：一眼看出几个在干活、几个歇着、几个在等你。
    """
    counts = {phase: sum(1 for s in sessions if s.get("phase") == phase) for phase, _ in _CAPSULE_PHASES}
    return [(phase, f"{counts[phase]} {text}") for phase, text in _CAPSULE_PHASES if counts[phase]]


def summarize_sessions(sessions: list[dict], *, detail_max: int = 2) -> tuple[str, str]:
    """把在用的会话汇总成两行：(各阶段计数, 前几个会话的「名 · 状态」)。

    灵动岛卡片用：第一行一眼看出有没有会话在等你，第二行点名最需要管的那几个。
    """
    live = [s for s in sessions if s.get("phase") in PHASE_TEXT]
    if not live:
        return "Claude Code · 没有在用的会话", "会话提问后会出现在这里"
    counts = {phase: sum(1 for s in live if s["phase"] == phase) for phase in _PHASE_ORDER}
    headline = "Claude Code · " + " · ".join(
        _PHASE_COUNT_TEXT[phase].format(n=counts[phase]) for phase in _PHASE_ORDER if counts[phase])
    ordered = sorted(live, key=lambda s: _PHASE_ORDER.index(s["phase"]))
    detail = " ｜ ".join(
        f"{session_label(str(s.get('agent') or ''), s)} · {PHASE_TEXT[s['phase']]}"
        for s in ordered[:detail_max])
    if len(ordered) > detail_max:
        detail += f" 等 {len(ordered)} 个"
    return headline, detail


# ---------------------------------------------------------------- 会话收敛

class ClaudeSessionTracker:
    """按会话记账，收敛成 Agent 级输出（纯逻辑，worker 线程内使用）。

    ``feed(record)`` 返回一串 ``(kind, payload)``：

    - ``("state", 状态)``：Agent 级状态，交给既有状态机；
    - ``("session_done", {...})``：一个会话收工，但同 Agent 还有别的会话在忙——
      只该弹一条提示，不能动状态机（否则桌宠会切回待机）；
    - ``("approval_request" | "approval_resolved", {"approvalId": ...})``：
      会话停在权限确认上 / 之后又动了。

    与通用映射（``agent_link.DEFAULT_EVENT_STATE_MAP``）的三处差异，都是 Claude
    Code 的实际语义决定的：

    - ``PostToolUseFailure`` 算 **working**：工具失败（grep 没匹配、测试没过）是
      常态，回合照常继续。按通用映射算 error 的话，模型多想 0.8 秒桌宠就会报
      「那边停了」。真正的回合失败是 ``StopFailure``。
    - ``SessionStart`` **不产生状态**：自动压缩上下文会在回合中途触发它
      （``source=compact``），当成 idle 会误报完成。
    - 非忙状态只在该会话**此前确实在忙**时才上报，避免空转会话的 Stop / SessionEnd
      打扰别的会话。
    """

    BUSY = ("thinking", "working")
    _EVENT_STATE = {
        "UserPromptSubmit": "thinking",
        "PreToolUse": "working",
        "PostToolUse": "working",
        "PostToolUseFailure": "working",
        "Stop": "attention",
        "StopFailure": "error",
        "SessionEnd": "idle",
    }
    _STATES = frozenset({"idle", "thinking", "working", "attention", "sleeping", "error"})
    #: 需要用户到 Claude Code 里点一下的通知类型
    _PROMPT_NTYPES = frozenset({"permission_prompt", "elicitation_dialog"})
    #: 会话表上限：被 Esc 打断的会话不发 Stop，会一直占着「忙」直到它的下一个事件。
    _MAX_SESSIONS = 64

    #: 标签文本（项目名 / 会话标题）的长度上限
    _LABEL_MAX = 40

    def __init__(self) -> None:
        self._busy: dict[str, str] = {}       # 会话 ID → thinking / working
        self._waiting: set[str] = set()       # 停在权限确认上的会话
        # 已「出场」的会话（提过问 / 被看到在干活）→ {"phase", "title", "project"}。
        # 逐会话呈现（会话小鱼）的数据源，与上面收敛成 Agent 级状态的记账互不影响。
        self._sessions: dict[str, dict[str, str]] = {}
        self._updates: list[dict[str, str]] = []

    def reset(self) -> None:
        self._busy.clear()
        self._waiting.clear()
        self._sessions.clear()
        self._updates.clear()

    def any_busy(self) -> bool:
        return bool(self._busy)

    def take_session_updates(self) -> list[dict[str, str]]:
        """取走自上次以来的逐会话更新：``{"sessionId", "phase", "title", "project"}``。

        ``phase``：``working``（在干活）/ ``waiting``（等用户批准）/ ``resting``
        （回合结束）/ ``gone``（会话关闭或被淘汰）。只在内容变化时产生一条；
        只开着没提过问的会话不出场。
        """
        updates, self._updates = self._updates, []
        return updates

    def _session_update(self, sid: str, *, phase: str = "", title: str = "", project: str = "",
                        born: bool = False) -> None:
        """改一个会话的呈现信息（空串 = 不改），有变化才记一条更新。"""
        info = self._sessions.get(sid)
        if info is None:
            if not born:
                return
            info = {"phase": "", "title": "", "project": ""}
            self._sessions[sid] = info
            while len(self._sessions) > self._MAX_SESSIONS:
                self._session_gone(next(iter(self._sessions)))
        changed = False
        for key, value in (("phase", phase), ("title", title), ("project", project)):
            if value and info[key] != value:
                info[key] = value
                changed = True
        if changed:
            self._updates.append({"sessionId": sid, **info})

    def end_all(self) -> None:
        """所有已出场的会话离场（通道被关掉时用）。"""
        for sid in list(self._sessions):
            self._session_gone(sid)

    def _session_gone(self, sid: str) -> None:
        info = self._sessions.pop(sid, None)
        if info is not None:
            self._updates.append({"sessionId": sid, **info, "phase": "gone"})

    @classmethod
    def _label(cls, value: Any) -> str:
        return " ".join(str(value or "").split())[:cls._LABEL_MAX]

    @staticmethod
    def _approval(sid: str) -> dict:
        return {"approvalId": f"claude-permission:{sid}"}

    def feed(self, record: dict) -> list[tuple[str, Any]]:
        event = str(record.get("event") or "")
        sid = str(record.get("sessionId") or "")
        out: list[tuple[str, Any]] = []
        resolved = False

        if event == "SessionMeta":
            self._session_update(sid, title=self._label(record.get("title")),
                                 project=self._label(record.get("project")))
            return out
        if event == "Notification":
            ntype = str(record.get("ntype") or "")
            if ntype in self._PROMPT_NTYPES:
                if sid not in self._waiting:
                    self._waiting.add(sid)
                    out.append(("approval_request", self._approval(sid)))
                self._session_update(sid, phase="waiting", born=True)
                return out
            if ntype != "idle_prompt" or sid not in self._busy:
                return out
            # 忙着的会话报「等输入已满 60 秒」：它其实早停了（被打断，没发 Stop）
            state = "attention"
        else:
            explicit = str(record.get("state") or "")
            state = explicit if explicit in self._STATES else self._EVENT_STATE.get(event, "")
            if sid in self._waiting:
                # 停在确认上的会话又有动静：用户已经答复（没有专门的「已答复」事件）
                self._waiting.discard(sid)
                out.append(("approval_resolved", self._approval(sid)))
                resolved = True
        if not state:
            if resolved:    # 答复了但这条记录不带状态：按它此刻是否还在忙归位
                self._session_update(sid, phase="working" if sid in self._busy else "resting")
            return out

        if state in self.BUSY:
            self._session_update(sid, phase="working", born=True)
            self._busy.pop(sid, None)
            self._busy[sid] = state            # 重新插到末尾：淘汰时先丢最久没动的
            while len(self._busy) > self._MAX_SESSIONS:
                self._busy.pop(next(iter(self._busy)))
            out.append(("state", state))
            return out

        if event == "SessionEnd":
            self._session_gone(sid)
        else:
            self._session_update(sid, phase="resting")
        was_busy = self._busy.pop(sid, None) is not None
        if not was_busy:
            return out
        if self._busy:
            if state != "idle":                # 会话被直接关掉（SessionEnd）不算收工
                out.append(("session_done", {"sessionId": sid, "state": state}))
            return out
        out.append(("state", state))
        return out
