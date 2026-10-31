# -*- coding: utf-8 -*-
"""会话记忆蒸馏·第一期：把我在 Claude Code 里说过的话（决定、偏好、纠正）从 transcript 抽进本地候选库。

用户 2026-10-30 的想法：每个会话里他发的消息里藏着决定和偏好，要收起来、定期总结、让以后的 Claude 都遵守。
设计评审定下的几条（都不在代码里看得出来，写在这）：

- **不另做记录**：Claude Code 自己把每条消息落在 ``~/.claude/projects/<目录编码>/<会话>.jsonl``，这里只增量读。
  ``~/.claude/history.jsonl`` 桌面版 / VS Code 不写，不能当源。
- **公司 / 个人按目录分，不按入口分**：实测桌面版开的 WSL 会话也存在 Windows 这边的 ``projects/ssh-*/`` 里，
  入口写的是 ``claude-desktop``；所以 POSIX 路径一律算公司侧，Windows 路径落在「公司目录」下也算。
  分流在抽取时就打上 ``side``，蒸馏（第二期）按侧各走各的账号，公司侧的话**根本不进**个人 key。
- **原始候选库放本地、不进 git**，按本地日期一天一个文件，滚动保留 90 天（git 里「滚动删除」删不掉历史）。
- 规则打标不用模型：``rule``（说了「以后 / always」）/ ``decision``（AskUserQuestion 的回答、「决定 / 就用」）/
  ``correction``（紧跟我动作后的否定）/ ``task``（其余，低优先级）。

本文件全是纯函数和文件读写，没有 Qt；阻塞的 ``CandidateStore.refresh`` 由调用方放后台线程。
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable

from . import work_briefing as wb

log = logging.getLogger("big-fat-fish")

CONFIG_KEY = "memory_distill"
STORE_DIR = "memory-distill"             # <配置目录>/memory-distill/
CANDIDATES_DIR = "candidates"
CURSORS_FILE = "cursors.json"
DEFAULT_KEEP_DAYS = 90
DEFAULT_DAILY_AT = "21:30"
DEFAULT_MODEL = "claude-sonnet-5-5"      # 个人 key 直连（个人助理同款）；第二期才真的调用
MAX_BEFORE_CHARS = 500                   # 「我问了什么」只留这么多
MAX_TEXT_CHARS = 4000                    # 用户一条话超过这个长度（多半是粘贴）只留开头

SIDE_PERSONAL = "personal"
SIDE_WORK = "work"
SIDES = (SIDE_PERSONAL, SIDE_WORK)

TAG_RULE = "rule"
TAG_DECISION = "decision"
TAG_CORRECTION = "correction"
TAG_TASK = "task"
TAGS = (TAG_RULE, TAG_DECISION, TAG_CORRECTION, TAG_TASK)

#: 系统往 user 记录里塞的块：整段剥掉，剩下的才是用户的话
_INJECTED_BLOCK_RE = re.compile(
    r"<(system-reminder|task-notification|ide_opened_file|ide_selection|local-command-caveat|local-command-stdout|"
    r"local-command-stderr|command-name|command-message|command-args|browser_instruction|bash-input|bash-stdout|"
    r"bash-stderr|create-pr-command|side-sessions-event|ci-monitor-event|pasted_content[^>]*)>.*?</\1>",
    re.DOTALL)
_INJECTED_TAG_RE = re.compile(r"</?[a-z][a-z0-9_-]{1,40}(?:\s[^>]*)?>", re.IGNORECASE)
#: 定时任务 / 监视器发来的消息以方括号标签开头（「[Ticket watch]」「[Request interrupted by user]」）
_BRACKET_PREFIX_RE = re.compile(r"^\s*\[[^\]\n]{1,60}\]")
_ACKS = frozenset({
    "ok", "okay", "k", "y", "yes", "yep", "sure", "go", "go ahead", "continue", "proceed", "done", "thanks", "thx",
    "好", "好的", "嗯", "行", "可以", "继续", "是", "是的", "对", "对的", "没问题", "谢谢", "收到", "开始", "做吧", "去吧",
})
_RULE_RE = re.compile(
    r"(以后|从现在起|从今往后|今后|往后|一律|永远|都要|记住|别再|不要再|不许|规矩|规则|约定|默认都|每次都|"
    r"from now on|going forward|in (?:the )?future|always|never|remember|every time|as a rule|by default|"
    r"do not .{0,30}anymore|don'?t .{0,30}anymore|no longer)", re.IGNORECASE)
_DECISION_RE = re.compile(
    r"(^\s*(决定|就用|选|用|就按|按|定了|定为|还是用)|不用\s*\S+\s*了?\s*[，,]?\s*用|"
    r"^\s*(let'?s go with|go with|let'?s use|we'?ll use|use|pick|choose|decision|decided|i'?ll take|option [a-z0-9])\b)",
    re.IGNORECASE)
_CORRECTION_RE = re.compile(
    r"(不对|不是这|不是我要|错了|弄错|搞错|改回|撤回|撤销|回退|别这样|不要这|不用这|不该|太大了|太小了|太长了|"
    r"not what i|that'?s wrong|wrong|don'?t|do not|instead|revert|undo|too (?:big|small|large|long)|"
    r"shouldn'?t|should not|stop)", re.IGNORECASE)

_HUMAN_ORIGINS = frozenset({"human", "typed"})


# ---------------------------------------------------------------- 分流与判噪


def default_work_root() -> str:
    """公司目录的默认值：用户的 ``WorkSpace``（AI-Base-Memory 副本、公司仓库都在那）。"""
    return str(Path.home() / "WorkSpace")


def classify_side(cwd: str, work_roots: Iterable[str]) -> str:
    """POSIX 路径 → 公司侧（WSL 里登录的是公司账号）；Windows 路径在某个公司目录下 → 公司侧；其余个人。"""
    path = str(cwd or "").strip()
    if not path:
        return SIDE_PERSONAL
    if path.startswith("/"):
        return SIDE_WORK
    try:
        parts = tuple(p.lower() for p in PureWindowsPath(path).parts)
    except (TypeError, ValueError):
        return SIDE_PERSONAL
    for root in work_roots:
        root_parts = tuple(p.lower() for p in PureWindowsPath(str(root)).parts)
        if root_parts and parts[:len(root_parts)] == root_parts:
            return SIDE_WORK
    return SIDE_PERSONAL


def clean_text(raw: str) -> str:
    """剥掉系统注入的块与标签，收紧空白；剩下的是用户自己敲的。"""
    text = _INJECTED_BLOCK_RE.sub("", str(raw or ""))
    text = _INJECTED_TAG_RE.sub("", text)
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line.strip()).strip()


def is_noise(text: str) -> bool:
    """空话、斜杠命令、系统标签打头的、只是一声「好」的——不进候选。"""
    body = str(text or "").strip()
    if not body or body.startswith("/") or body.startswith("<"):
        return True
    if _BRACKET_PREFIX_RE.match(body):
        return True
    return body.lower().rstrip("。.!！~") in _ACKS


def tag_for(text: str) -> str:
    """规则 > 决定 > 纠正 > 任务。只看文字，不用模型。"""
    body = str(text or "")
    if _RULE_RE.search(body):
        return TAG_RULE
    if _DECISION_RE.search(body):
        return TAG_DECISION
    if _CORRECTION_RE.search(body):
        return TAG_CORRECTION
    return TAG_TASK


def is_human_turn(record: dict) -> bool:
    """主链上、人敲的 user 记录。定时任务 / 子会话回传 / 同伴消息都有 ``origin.kind`` 或 ``turnOrigin`` 标记。"""
    if record.get("type") != "user" or record.get("isSidechain"):
        return False
    origin = record.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
        return False
    turn = record.get("turnOrigin")
    return turn is None or turn in _HUMAN_ORIGINS


def _text_blocks(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [str(block.get("text") or "") for block in content
                if isinstance(block, dict) and block.get("type") == "text"]
    return []


def _has_tool_result(content) -> bool:
    return isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


# ---------------------------------------------------------------- 抽取


@dataclass
class Candidate:
    id: str                       # user 记录的 uuid（去重键）
    time: str                     # 记录时间，ISO（UTC）
    side: str                     # personal / work
    project: str                  # cwd
    session_id: str
    entrypoint: str
    branch: str
    before: str                   # 我上一条正文（截断）——「Claude 问了什么」
    text: str                     # 用户的话（或「问 → 答」）
    tag: str
    question: str = ""            # AskUserQuestion 的问题
    answer: str = ""

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self), ensure_ascii=False)


@dataclass
class ScanState:
    """一个 transcript 的游标：读到哪个字节、文件多大、开头指纹（文件被整个重写时认得出）、
    上一条 assistant 正文（跨次扫描还记得「问了什么」）。"""
    offset: int = 0
    size: int = 0
    before: str = ""
    head: str = ""

    def to_dict(self) -> dict:
        return {"offset": self.offset, "size": self.size, "before": self.before, "head": self.head}

    @classmethod
    def from_dict(cls, data) -> "ScanState":
        data = data if isinstance(data, dict) else {}
        try:
            return cls(offset=max(0, int(data.get("offset", 0))), size=max(0, int(data.get("size", 0))),
                       before=str(data.get("before") or ""), head=str(data.get("head") or ""))
        except (TypeError, ValueError):
            return cls()


def _ask_answers(record: dict) -> list[tuple[str, str]]:
    """AskUserQuestion 的 tool_result 记录自带 ``toolUseResult.answers``（问 → 答），不用回头找 tool_use。"""
    result = record.get("toolUseResult")
    if not isinstance(result, dict):
        return []
    answers = result.get("answers")
    if not isinstance(answers, dict):
        return []
    return [(str(q).strip(), str(a).strip()) for q, a in answers.items() if str(q).strip() and str(a).strip()]


def _candidate_from(record: dict, *, text: str, tag: str, before: str, work_roots: Iterable[str],
                    suffix: str = "", question: str = "", answer: str = "") -> Candidate:
    cwd = str(record.get("cwd") or "")
    return Candidate(
        id=str(record.get("uuid") or "") + suffix, time=str(record.get("timestamp") or ""),
        side=classify_side(cwd, work_roots), project=cwd, session_id=str(record.get("sessionId") or ""),
        entrypoint=str(record.get("entrypoint") or ""), branch=str(record.get("gitBranch") or ""),
        before=before, text=text, tag=tag, question=question, answer=answer)


def extract(text: str, *, work_roots: Iterable[str], state: ScanState | None = None) -> tuple[list[Candidate], ScanState]:
    """从 transcript 全文（或其前缀）抽候选。``state`` 是上次读到的位置：只处理新字节、只处理以换行结尾的整行。"""
    state = state or ScanState()
    data = text.encode("utf-8")
    end = data.rfind(b"\n", state.offset) + 1
    if end <= state.offset:
        return [], ScanState(offset=state.offset, size=len(data), before=state.before)
    work_roots = tuple(work_roots)
    before = state.before
    found: list[Candidate] = []
    for raw in data[state.offset:end].decode("utf-8", errors="replace").split("\n"):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("isSidechain"):
            continue
        kind = record.get("type")
        content = (record.get("message") or {}).get("content") if isinstance(record.get("message"), dict) else None
        if kind == "assistant":
            spoken = clean_text("\n".join(_text_blocks(content)))
            if spoken:
                before = _clip(spoken, MAX_BEFORE_CHARS)
            continue
        if kind != "user":
            continue
        if _has_tool_result(content):
            for index, (question, answer) in enumerate(_ask_answers(record)):
                found.append(_candidate_from(record, text=f"{question} → {answer}", tag=TAG_DECISION, before=before,
                                             work_roots=work_roots, suffix=f"#{index}" if index else "",
                                             question=question, answer=answer))
            continue
        if not is_human_turn(record):
            continue
        spoken = clean_text("\n".join(_text_blocks(content)))
        if is_noise(spoken):
            continue
        found.append(_candidate_from(record, text=_clip(spoken, MAX_TEXT_CHARS), tag=tag_for(spoken), before=before,
                                     work_roots=work_roots))
    return found, ScanState(offset=end, size=len(data), before=before)


# ---------------------------------------------------------------- 候选库


def projects_dir(home: Path | None = None) -> Path:
    """Claude Code 的 transcript 根目录 ``~/.claude/projects``。"""
    return (home or Path.home()) / ".claude" / "projects"


def iter_transcripts(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        try:
            yield from sorted(Path(root).glob("*/*.jsonl"))
        except OSError:
            continue


HEAD_BYTES = 256


def _fingerprint(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:16]


def _local_day(stamp: str) -> str:
    try:
        when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return dt.date.today().isoformat()
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.astimezone().date().isoformat()


class CandidateStore:
    """本地候选库：``<root>/candidates/<本地日期>.jsonl`` + ``<root>/cursors.json``。不进 git。"""

    def __init__(self, root: Path, *, keep_days: int = DEFAULT_KEEP_DAYS) -> None:
        self.root = Path(root)
        self.keep_days = max(1, int(keep_days))
        self.candidates_dir = self.root / CANDIDATES_DIR
        self.cursors_path = self.root / CURSORS_FILE
        self.last_refresh: str = ""
        self.last_added: int = 0

    # -- 游标 --
    def load_cursors(self) -> dict[str, ScanState]:
        try:
            data = json.loads(self.cursors_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        files = data.get("files") if isinstance(data.get("files"), dict) else data
        self.last_refresh = str(data.get("last_refresh") or "") if "files" in data else ""
        return {str(k): ScanState.from_dict(v) for k, v in files.items()}

    def save_cursors(self, cursors: dict[str, ScanState]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {"last_refresh": self.last_refresh, "files": {k: v.to_dict() for k, v in cursors.items()}}
        tmp = self.cursors_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.cursors_path)

    # -- 抽取 --
    def refresh(self, roots: Iterable[Path], *, work_roots: Iterable[str]) -> int:
        """增量扫所有 transcript，新候选追加进当天文件；返回新增条数。阻塞：读文件。"""
        cursors = self.load_cursors()
        work_roots = tuple(work_roots)
        added = 0
        seen: set[str] = set()
        for path in iter_transcripts(roots):
            key = str(path)
            seen.add(key)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            state = cursors.get(key, ScanState())
            try:
                with path.open("rb") as handle:
                    head = _fingerprint(handle.read(HEAD_BYTES))
                    if size < state.offset or head != state.head:     # 变短或开头变了 = 文件被重写：从头再来
                        state = ScanState()
                    if size == state.offset:
                        cursors[key] = ScanState(offset=state.offset, size=size, before=state.before, head=head)
                        continue
                    handle.seek(state.offset)
                    chunk = handle.read()
            except OSError:
                continue
            found, tail = extract(chunk.decode("utf-8", errors="replace"), work_roots=work_roots,
                                  state=ScanState(offset=0, size=0, before=state.before))
            cursors[key] = ScanState(offset=state.offset + tail.offset, size=size, before=tail.before, head=head)
            if found:
                self.append(found)
                added += len(found)
        for key in list(cursors):
            if key not in seen and not Path(key).exists():
                cursors.pop(key)
        self.last_refresh = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        self.last_added = added
        self.save_cursors(cursors)
        return added

    def append(self, candidates: Iterable[Candidate]) -> None:
        self.candidates_dir.mkdir(parents=True, exist_ok=True)
        by_day: dict[str, list[Candidate]] = {}
        for item in candidates:
            by_day.setdefault(_local_day(item.time), []).append(item)
        for day, items in by_day.items():
            with (self.candidates_dir / f"{day}.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
                for item in items:
                    handle.write(item.to_json() + "\n")

    # -- 读 --
    def day_files(self) -> list[Path]:
        try:
            return sorted(p for p in self.candidates_dir.glob("*.jsonl") if _DAY_RE.fullmatch(p.stem))
        except OSError:
            return []

    def read_day(self, day: str) -> list[dict]:
        path = self.candidates_dir / f"{day}.jsonl"
        rows: list[dict] = []
        try:
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict):
                        rows.append(row)
        except OSError:
            pass
        return rows

    def read_all(self) -> list[dict]:
        rows: list[dict] = []
        for path in self.day_files():
            rows.extend(self.read_day(path.stem))
        return rows

    # -- 清理与统计 --
    def prune(self, *, today: dt.date | None = None) -> list[str]:
        """删掉早于保留期的日文件；返回删掉的日期。"""
        today = today or dt.date.today()
        cutoff = today - dt.timedelta(days=self.keep_days)
        removed: list[str] = []
        for path in self.day_files():
            try:
                if dt.date.fromisoformat(path.stem) < cutoff:
                    path.unlink()
                    removed.append(path.stem)
            except (ValueError, OSError):
                continue
        return removed

    def stats(self) -> dict:
        files = self.day_files()
        today = dt.date.today().isoformat()
        total = today_count = 0
        by_side: Counter = Counter()
        by_tag: Counter = Counter()
        for path in files:
            rows = self.read_day(path.stem)
            total += len(rows)
            if path.stem == today:
                today_count = len(rows)
            by_side.update(r.get("side", SIDE_PERSONAL) for r in rows)
            by_tag.update(r.get("tag", TAG_TASK) for r in rows)
        if not self.last_refresh:
            self.load_cursors()
        return {"total": total, "today": today_count, "days": len(files), "files": len(self.load_cursors()),
                "by_side": dict(by_side), "by_tag": dict(by_tag), "last_refresh": self.last_refresh,
                "first_day": files[0].stem if files else "", "root": str(self.root)}


_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


# ---------------------------------------------------------------- 配置


def _normalize_roots(value) -> list[str]:
    """公司目录列表：只认字符串列表（配置手写成一个字符串算写错，退回默认）。"""
    if not isinstance(value, list):
        return [default_work_root()]
    roots = [str(item).strip() for item in value if isinstance(item, str) and str(item).strip()]
    return roots or [default_work_root()]


def _normalize_days(value) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return DEFAULT_KEEP_DAYS
    return days if 1 <= days <= 3650 else DEFAULT_KEEP_DAYS


_TIME_RE = re.compile(r"\s*(\d{1,2})(?::(\d{2}))?\s*")


def normalize_time(value) -> str:
    """``7:05`` / ``21`` → ``HH:MM``；不是一个时刻就退回默认（和工作简报同一套写法，默认值不同）。"""
    match = _TIME_RE.fullmatch(str(value if value is not None else ""))
    if not match:
        return DEFAULT_DAILY_AT
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    return f"{hour:02d}:{minute:02d}" if hour < 24 and minute < 60 else DEFAULT_DAILY_AT


def normalize(value) -> dict:
    """配置节 ``memory_distill``：开关、保留天数、公司目录、每日时刻、模型 / effort / 提示词（第二期才用，
    但按规矩一开始就明文摆出来）。"""
    data = value if isinstance(value, dict) else {}
    model = str(data.get("model") or "").strip()
    return {
        "enabled": bool(data.get("enabled", False)),
        "keep_days": _normalize_days(data.get("keep_days", DEFAULT_KEEP_DAYS)),
        "work_roots": _normalize_roots(data.get("work_roots")),
        "daily_at": normalize_time(data.get("daily_at", DEFAULT_DAILY_AT)),
        "model": model if model and wb.normalize_model(model) == model else DEFAULT_MODEL,
        "effort": wb.normalize_effort(data.get("effort", wb.EFFORT)),
        "prompt_zh": wb.normalize_text(data.get("prompt_zh")),
        "prompt_en": wb.normalize_text(data.get("prompt_en")),
    }


def store_root(config_dir: Path) -> Path:
    return Path(config_dir) / STORE_DIR


def store_for(config, config_dir: Path) -> CandidateStore:
    settings = normalize(config.get(CONFIG_KEY) if hasattr(config, "get") else config)
    return CandidateStore(store_root(config_dir), keep_days=settings["keep_days"])


def posix_home_label(path: str) -> str:
    """给页面看的短项目名：Windows 路径取最后一段，POSIX 也取最后一段。"""
    if not path:
        return ""
    return (PurePosixPath(path) if path.startswith("/") else PureWindowsPath(path)).name or path


# ---------------------------------------------------------------- 蒸馏提示词（第二期发给模型；第一期先明文摆在设置里）

_PROMPTS = {
    "zh": """你在整理一个人在 Claude Code 里说过的话，目的是提炼出以后每个会话都该遵守的记忆条目。

下面是今天的候选（每条有：时间、项目、标签、Claude 当时说了什么、这个人说了什么），以及现有的记忆文件全文。

候选：
{candidates}

现有记忆：
{memory}

请输出一份对现有记忆的变更提案，JSON 数组，每项：
{"action": "add|change|retire", "scope": "global|project", "project": "", "type": "user|feedback|project",
 "title": "一句话", "why": "为什么", "how": "怎么用", "evidence": ["日期 项目：原话"], "replaces": "被改 / 作废的条目标题"}

规则：
- 明说了「以后 / 从现在起 / always / never」的，一条就算；没明说的习惯，至少在两个不同会话里出现才算。
- 一次性的任务指令（「这个 PR 用 X」）不升级成规则。
- 已经写在现有记忆里、而且今天没有被纠正的，不要重复提。
- 今天纠正了现有记忆里某条的，提 change 并引用原话。
- 没有可提的就输出 []。""",
    "en": """You are distilling what one person said in Claude Code into memory entries that every later session should follow.

Below are today's candidates (each with time, project, tag, what Claude had said, what the person said) and the full text of the existing memory files.

Candidates:
{candidates}

Existing memory:
{memory}

Output a change proposal against the existing memory as a JSON array; each item:
{"action": "add|change|retire", "scope": "global|project", "project": "", "type": "user|feedback|project",
 "title": "one sentence", "why": "why", "how": "how to apply", "evidence": ["date project: quote"], "replaces": "title of the entry changed / retired"}

Rules:
- An explicit "from now on / always / never" counts once; an unstated habit needs at least two different sessions.
- One-off task instructions ("use X for this PR") do not become rules.
- Do not repeat what the existing memory already says unless it was corrected today.
- If today corrected an existing entry, propose a change and quote the words.
- Output [] when there is nothing to propose.""",
}


def default_prompt_template(language: str | None = None) -> str:
    """内置提示词（按界面语言）；用户在设置里改过就用他的（``prompt_zh`` / ``prompt_en``）。占位符
    ``{candidates}`` / ``{memory}`` 由第二期的 ``render_template`` 填。"""
    return _PROMPTS[wb.prompt_language(language)]


def prompt_template(settings: dict, language: str | None = None) -> str:
    language = wb.prompt_language(language)
    return settings.get(f"prompt_{language}") or default_prompt_template(language)


__all__ = [name for name in dir() if not name.startswith("_")]
