# -*- coding: utf-8 -*-
"""会话记忆蒸馏·第三期（公司侧）——所有要进 WSL 才能做的事都经这里，全部走 ``wsl.exe``（``claude_hooks.run_wsl``）。

为什么要有公司侧：用户工作时在 WSL 里用登录**公司账号**的 Claude Code，那边的会话记录写在 WSL 自己的
``~/.claude/projects``，Windows 这边扫不到（桌面版开的 WSL 会话例外，它们存在 Windows 的 ``projects/ssh-*``）。

- 抽取：默认发行版在不在跑、那边有哪些 transcript。
- 蒸馏：公司侧候选只交给那边的公司账号（``claude -p``，提示词走标准输入）。**绝不**调个人 key 的
  ``anthropic_provider.complete``——公司会话的原话不能进个人账号。现有记忆（WSL 里的 CLAUDE.md、项目 MEMORY.md）
  也在那边读。

都是阻塞调用，放后台线程。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from . import claude_hooks
from . import memory_distill as md
from . import memory_distill_run as run
from . import work_briefing as wb
from . import work_notes as wn
from .i18n import t

WslRunner = Callable[..., tuple[int, str]]

CLAUDE_TIMEOUT_S = 600.0       # 和工作简报 / 笔记同一个上限：claude -p 自己起来就要十来秒
LIST_TIMEOUT_S = 30.0          # 发行版冷启动要几秒
STATE_TIMEOUT_S = 10.0
#: 第一行：projects 目录在 Windows 这边的路径；之后每行「字节数<TAB>项目目录/会话.jsonl」。目录不存在只出第一行都没有。
LIST_COMMAND = ('d="$HOME/.claude/projects"; [ -d "$d" ] || exit 0; wslpath -w "$d"; '
                'find "$d" -mindepth 2 -maxdepth 2 -type f -name "*.jsonl" -printf "%s\\t%P\\n"')


def default_distro_running(runner: WslRunner = claude_hooks.run_wsl) -> bool:
    """默认发行版此刻在不在跑（``wsl.exe -l -v`` 里带 ``*`` 的那行）。这条命令本身不会把发行版拉起来。

    定时抽取靠它决定要不要去 WSL：没在跑就说明上次扫过之后那边最多只多了关机前的一小段，没必要为了每小时
    一次的增量把整个发行版叫醒（别的发行版——比如 docker-desktop——在跑不算）。"""
    try:
        code, out = runner(["-l", "-v"], timeout=STATE_TIMEOUT_S)
    except Exception:  # noqa: BLE001 - 问不到就当没在跑
        return False
    if code != 0:
        return False
    for line in out.splitlines():
        if line.lstrip().startswith("*"):
            return "running" in line.lower()
    return False


def list_transcripts(runner: WslRunner = claude_hooks.run_wsl) -> md.RemoteListing | None:
    """默认发行版里 ``~/.claude/projects/*/*.jsonl`` 的清单（一次 ``find``，实测 91 个文件 0.1 s）。

    会把没在跑的发行版拉起来。问不到返回 None——和「问到了、一个文件都没有」不是一回事：前者不能动那边的游标。"""
    try:
        code, out = runner(["-e", "sh", "-c", LIST_COMMAND], timeout=LIST_TIMEOUT_S)
    except Exception:  # noqa: BLE001
        return None
    lines = [line.rstrip("\r") for line in out.splitlines() if line.strip()]
    if code != 0 or not lines or not _looks_like_dir(lines[0]):
        return None
    files: list[tuple[str, int]] = []
    for line in lines[1:]:
        size, sep, rel = line.partition("\t")
        if not sep or not size.strip().isdigit() or not rel.endswith(".jsonl"):
            continue
        files.append((rel.strip(), int(size)))
    return md.RemoteListing(root=lines[0].strip(), files=tuple(sorted(files)))


# ---------------------------------------------------------------- 蒸馏：WSL 里的公司账号


class WslError(RuntimeError):
    """WSL 里的 ``claude -p`` 没给出能用的结果；消息是给人看的原因。"""


@dataclass
class Completion:
    """和个人侧 ``anthropic_provider.complete`` 的返回值同样的几个字段，``memory_distill_run.run_once`` 只认这些。"""
    text: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""
    cost_usd: float = 0.0


def claude_command(model: str, effort: str, *, max_tokens: int = 0) -> str:
    """在发行版的登录 shell 里跑的那一行；提示词从标准输入进去。

    和工作简报那条（``work_briefing.claude_command``）的区别：一个工具都不给（只要它读提示词、写 JSON）、一轮就完。
    ``--no-session-persistence``：不留会话记录——不然蒸馏的提示词（里面全是候选原话）会被下一轮抽取当成
    「我说过的话」抽回来。``HEADLESS_ENV``：肥鱼自己的钩子认它，不把这次调用当成一个要显示的会话。"""
    limit = f" CLAUDE_CODE_MAX_OUTPUT_TOKENS={int(max_tokens)}" if int(max_tokens or 0) > 0 else ""
    return (f"cd ~ && {claude_hooks.HEADLESS_ENV}=1{limit} claude -p --model {wb._sq(wb.normalize_model(model))}"
            f" --effort {wb.normalize_effort(effort)} --output-format json --no-session-persistence"
            f" --max-turns 1 --tools ''")


def make_complete(runner: WslRunner = claude_hooks.run_wsl) -> Callable:
    """给 ``run_once`` 用的 ``complete``：签名和个人侧那个一样，但请求发给 WSL 里登录着公司账号的 Claude Code。

    ``provider`` 参数不用（公司账号是订阅登录，凭证不出 WSL）；失败一律抛 ``WslError``。"""

    def complete(prompt: str, system: str = "", provider=None, *, model: str = "", effort: str = "",
                 timeout: float | None = None, max_tokens: int = 0) -> Completion:
        del system, provider
        code, out = runner(["-e", "bash", "-lc", claude_command(model, effort, max_tokens=max_tokens)],
                           input_text=prompt, timeout=max(float(timeout or 0.0), CLAUDE_TIMEOUT_S))
        if code == 127 and not out:
            raise WslError(t("distill.work.no_wsl"))
        record = wb._result_record(out)
        if record is None:
            tail = " ".join(str(out or "").split())[-160:]
            raise WslError(t("distill.work.no_result", tail=tail) if tail else t("distill.work.no_output", code=code))
        text = str(record.get("result") or "").strip()
        if record.get("is_error") or record.get("subtype") not in (None, "success") or not text:
            reason = " ".join(text.split())[:160] or str(record.get("subtype") or "")
            raise WslError(t("distill.work.failed", reason=reason) if reason else t("distill.work.empty"))
        model_used, tokens_in, tokens_out, cost = wn.usage_of(record)
        return Completion(text=text, model=model_used or model, input_tokens=tokens_in, output_tokens=tokens_out,
                          stop_reason=str(record.get("stop_reason") or ""), cost_usd=cost)

    return complete


# ---------------------------------------------------------------- 现有记忆（在 WSL 里）

FILE_MARK = "@@BFF-FILE@@"
MAX_FILE_BYTES = 16000
READ_TIMEOUT_S = 30.0
GLOBAL_CLAUDE_MD = "$HOME/.claude/CLAUDE.md"


def project_memory_dir(cwd: str) -> str:
    """WSL 里这个项目的 memory 目录（shell 里用的写法，``$HOME`` 留给那边展开）。目录编码和 Windows 侧同一套。"""
    return f"$HOME/.claude/projects/{run.encode_project_dir(cwd)}/memory"


def read_command(paths: Iterable[str]) -> str:
    """一次读多个文件：存在的每个先出一行「标记 + 传进来的那个写法」，再出文件开头 ``MAX_FILE_BYTES`` 字节。

    路径只来自 ``GLOBAL_CLAUDE_MD`` / ``project_memory_dir``（编码后只有字母数字和 ``-``），可以放进双引号里。"""
    calls = " ".join(f"p {wb._sq(path)} \"{path}\";" for path in paths)
    return (f"p() {{ [ -f \"$2\" ] || return 0; printf '\\n%s %s\\n' '{FILE_MARK}' \"$1\"; head -c {MAX_FILE_BYTES} \"$2\"; }}; "
            f"{calls}")


def read_files(paths: Iterable[str], runner: WslRunner = claude_hooks.run_wsl) -> dict[str, str]:
    """{传进来的写法: 内容}；不存在的不在结果里。问不到返回空表。"""
    wanted = list(dict.fromkeys(paths))
    if not wanted:
        return {}
    try:
        code, out = runner(["-e", "sh", "-c", read_command(wanted)], timeout=READ_TIMEOUT_S)
    except Exception:  # noqa: BLE001
        return {}
    if code != 0:
        return {}
    found: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    for line in out.splitlines():
        if line.startswith(FILE_MARK + " "):
            if current is not None:
                found[current] = "\n".join(lines).strip()
            current, lines = line[len(FILE_MARK) + 1:].strip(), []
        elif current is not None:
            lines.append(line)
    if current is not None:
        found[current] = "\n".join(lines).strip()
    return {path: body for path, body in found.items() if path in wanted}


def memory_context(rows: Iterable[dict], *, runner: WslRunner = claude_hooks.run_wsl, entries_text: str = "") -> str:
    """送给公司账号看的「现有记忆」：WSL 里的全局 CLAUDE.md、本次候选涉及的每个项目的 MEMORY.md 索引。

    和 ``memory_distill_run.memory_context`` 同样的形状与上限，只是文件在 WSL 里、一次 wsl.exe 读完。"""
    projects: dict[str, str] = {}
    for row in rows:
        cwd = run.repo_root(str(row.get("project") or ""))
        if cwd and cwd not in projects:
            projects[cwd] = project_memory_dir(cwd) + "/MEMORY.md"
    files = read_files([GLOBAL_CLAUDE_MD, *projects.values()], runner)
    parts = [f"### 全局 ~/.claude/CLAUDE.md（WSL）\n{_clip(files.get(GLOBAL_CLAUDE_MD, '')) or '(空)'}"]
    if entries_text:
        parts.append(f"### 已落盘的蒸馏条目\n{entries_text}")
    for cwd, path in projects.items():
        index = _clip(files.get(path, ""))
        if index:
            parts.append(f"### 项目 {cwd} 的 memory/MEMORY.md\n{index}")
    out = "\n\n".join(parts)
    return out if len(out) <= run.MAX_MEMORY_TOTAL_CHARS else out[:run.MAX_MEMORY_TOTAL_CHARS - 1] + "…"


def _clip(text: str, limit: int = run.MAX_MEMORY_FILE_CHARS) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _looks_like_dir(line: str) -> bool:
    """``wslpath -w`` 的输出：UNC（``\\\\wsl.localhost\\…``）或盘符路径（``/`` 开头的绝对路径也认，测试在
    非 Windows 上跑时临时目录长这样）。登录横幅之类的别的字不算。"""
    text = line.strip()
    return text.startswith(("\\\\", "/")) or (len(text) > 2 and text[1] == ":" and text[2] in "\\/")


__all__ = [name for name in dir() if not name.startswith("_")]
