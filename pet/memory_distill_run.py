# -*- coding: utf-8 -*-
"""会话记忆蒸馏·第二期——蒸馏这一步：挑候选、读现有记忆、拼提示词、调模型、解析成提案、存进提案库。

只做个人侧（公司侧是第三期，在 WSL 里用公司账号）。全是纯函数 + 文件读写；模型调用由调用方注入
（``complete``），测试里用假函数。每日一次 + 手动：``is_due`` 和工作简报同一套「到点、今天没做过、
刚失败过就歇 20 分钟、一天最多 3 次」。

提案（``Proposal``）是对**现有记忆**的变更：add / change / retire，带原话证据；用户逐条接受 / 改 / 拒，
拒的进「别再提」名单（下次拼提示词时告诉模型）。落盘见 ``memory_distill_sink``。
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from . import memory_distill as md
from . import work_briefing as wb

STATE_FILE = "distill-state.json"
PROPOSALS_FILE = "proposals.json"
MAX_ATTEMPTS_PER_DAY = 3
RETRY_AFTER_S = 20 * 60
MAX_CANDIDATES_PER_RUN = 150          # 超了先丢「任务」，再丢最老的
MAX_TEXT_PER_CANDIDATE = 600
MAX_BEFORE_PER_CANDIDATE = 200
MAX_MEMORY_FILE_CHARS = 4000          # 每个 MEMORY.md / CLAUDE.md 最多送这么多
MAX_MEMORY_TOTAL_CHARS = 24000
TIMEOUT_S = 300.0                     # 实测 150 条候选 + high 强度一次 196 s
MAX_TOKENS = 32000                    # 实测默认 16000 几乎全花在思考上，正文被截断

ACTIONS = ("add", "change", "retire")
SCOPES = ("global", "project")
TYPES = ("user", "feedback", "project")
STATUS_PENDING, STATUS_ACCEPTED, STATUS_REJECTED, STATUS_SKIPPED = "pending", "accepted", "rejected", "skipped"
STATUSES = (STATUS_PENDING, STATUS_ACCEPTED, STATUS_REJECTED, STATUS_SKIPPED)

_PRIORITY = {md.TAG_RULE: 0, md.TAG_DECISION: 0, md.TAG_CORRECTION: 1, md.TAG_TASK: 2}
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_WORKTREE_RE = re.compile(r"[\\/]\.claude[\\/]worktrees[\\/][^\\/]+", re.IGNORECASE)


# ---------------------------------------------------------------- 定时


def is_due(settings: dict, state: dict, now: dt.datetime) -> bool:
    """到点了、今天还没做、也没有刚失败过 / 失败太多次。"""
    if not settings.get("enabled"):
        return False
    hour, minute = (int(part) for part in md.normalize_time(settings.get("daily_at")).split(":"))
    if (now.hour, now.minute) < (hour, minute):
        return False
    today = now.date().isoformat()
    if state.get("done_date") == today:
        return False
    if state.get("attempt_date") == today:
        if int(state.get("attempts") or 0) >= MAX_ATTEMPTS_PER_DAY:
            return False
        if now.timestamp() - float(state.get("last_attempt") or 0.0) < RETRY_AFTER_S:
            return False
    return True


def load_state(root: Path | str) -> dict:
    try:
        data = json.loads((Path(root) / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(root: Path | str, state: dict) -> None:
    path = Path(root) / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def mark_attempt(state: dict, now: dt.datetime) -> dict:
    today = now.date().isoformat()
    attempts = int(state.get("attempts") or 0) + 1 if state.get("attempt_date") == today else 1
    return {**state, "attempt_date": today, "attempts": attempts, "last_attempt": now.timestamp()}


# ---------------------------------------------------------------- 挑候选


def select_candidates(rows: Iterable[dict], state: dict, *, side: str = md.SIDE_PERSONAL,
                      limit: int = MAX_CANDIDATES_PER_RUN) -> tuple[list[dict], str]:
    """上次蒸馏之后、这一侧的候选，按时间排；超预算先丢「任务」、再丢最老的。返回 (候选, 最新一条的时间)。"""
    since = str(state.get("last_candidate_time") or "")
    picked = sorted((r for r in rows if r.get("side", md.SIDE_PERSONAL) == side and str(r.get("time") or "") > since),
                    key=lambda r: str(r.get("time") or ""))
    newest = str(picked[-1].get("time") or "") if picked else since
    if len(picked) > limit:
        keep = sorted(picked, key=lambda r: (_PRIORITY.get(r.get("tag"), 2), -_ts(r)))[:limit]
        picked = sorted(keep, key=lambda r: str(r.get("time") or ""))
    return picked, newest


def _ts(row: dict) -> float:
    try:
        return dt.datetime.fromisoformat(str(row.get("time") or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _local(stamp: str) -> str:
    try:
        when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return stamp[:16]
    return when.astimezone().strftime("%Y-%m-%d %H:%M") if when.tzinfo else when.strftime("%Y-%m-%d %H:%M")


def format_candidates(rows: Iterable[dict]) -> str:
    """给模型看的候选清单，一条一行：时间 | 项目 | 标签 | Claude 说 → 我说。"""
    lines = []
    for row in rows:
        before = " ".join(str(row.get("before") or "").split())[:MAX_BEFORE_PER_CANDIDATE]
        text = " ".join(str(row.get("text") or "").split())[:MAX_TEXT_PER_CANDIDATE]
        head = f"- [{_local(str(row.get('time') or ''))} | {md.posix_home_label(str(row.get('project') or ''))} | {row.get('tag') or ''}]"
        lines.append(f"{head} Claude: “{before}” → 我: “{text}”" if before else f"{head} 我: “{text}”")
    return "\n".join(lines)


# ---------------------------------------------------------------- 现有记忆


def repo_root(cwd: str) -> str:
    """worktree（``<仓库>\\.claude\\worktrees\\<名>``）的会话归主仓库——Claude Code 的 memory 目录也是这么归的。"""
    return _WORKTREE_RE.sub("", str(cwd or ""))


def encode_project_dir(cwd: str) -> str:
    """Claude Code 的目录编码：所有非字母数字换成 ``-``（``C:\\Users\\me\\Pet`` → ``C--Users-me-Pet``）。"""
    return re.sub(r"[^A-Za-z0-9]", "-", repo_root(cwd))


def project_dir(cwd: str, projects_root: Path | str) -> Path:
    """这个 cwd 对应的 ``~/.claude/projects/<编码>``：已有的目录按大小写不敏感匹配（本机同一仓库出现过 ``C--`` 和 ``c--`` 两种）。"""
    root = Path(projects_root)
    wanted = encode_project_dir(cwd)
    try:
        for child in root.iterdir():
            if child.is_dir() and child.name.lower() == wanted.lower():
                return child
    except OSError:
        pass
    return root / wanted


def memory_context(rows: Iterable[dict], *, home: Path | None = None, projects_root: Path | None = None,
                   claude_md: Path | None = None, entries_text: str = "") -> str:
    """送给模型的「现有记忆」：全局 CLAUDE.md（含受管块）、本次候选涉及的每个项目的 MEMORY.md 索引，各有上限。"""
    home = home or Path.home()
    projects_root = projects_root or md.projects_dir(home)
    claude_md = claude_md or (home / ".claude" / "CLAUDE.md")
    parts: list[str] = []
    text = _read(claude_md)
    parts.append(f"### 全局 ~/.claude/CLAUDE.md\n{text or '(空)'}")
    if entries_text:
        parts.append(f"### 已落盘的蒸馏条目\n{entries_text}")
    seen: set[str] = set()
    for row in rows:
        cwd = repo_root(str(row.get("project") or ""))
        key = cwd.lower()
        if not cwd or key in seen:
            continue
        seen.add(key)
        index = _read(project_dir(cwd, projects_root) / "memory" / "MEMORY.md")
        if index:
            parts.append(f"### 项目 {cwd} 的 memory/MEMORY.md\n{index}")
    out = "\n\n".join(parts)
    return out if len(out) <= MAX_MEMORY_TOTAL_CHARS else out[:MAX_MEMORY_TOTAL_CHARS - 1] + "…"


def _read(path: Path, limit: int = MAX_MEMORY_FILE_CHARS) -> str:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    text = text.strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


# ---------------------------------------------------------------- 提案


@dataclass
class Proposal:
    id: str
    action: str                       # add / change / retire
    scope: str                        # global / project
    project: str                      # scope=project 时的 cwd（模型给的项目名会被对回候选里的 cwd）
    type: str                         # user / feedback / project
    title: str
    why: str = ""
    how: str = ""
    evidence: list[str] = field(default_factory=list)
    replaces: str = ""
    status: str = STATUS_PENDING
    run_at: str = ""
    reviewed_at: str = ""
    applied: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Proposal":
        known = {f.name for f in dataclasses.fields(cls)}
        clean = {k: v for k, v in (data or {}).items() if k in known}
        clean.setdefault("id", "")
        clean.setdefault("action", "add")
        clean.setdefault("scope", "global")
        clean.setdefault("project", "")
        clean.setdefault("type", "feedback")
        clean.setdefault("title", "")
        if not isinstance(clean.get("evidence"), list):
            clean["evidence"] = []
        if not isinstance(clean.get("applied"), dict):
            clean["applied"] = {}
        return cls(**clean)


def proposal_id(action: str, scope: str, project: str, title: str) -> str:
    key = "|".join((action, scope, project.lower(), " ".join(title.split()).lower()))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def _json_array(text: str):
    """模型输出里的那个 JSON 数组：优先代码围栏里的，否则第一个 ``[`` 起。输出被截断（max_tokens 到顶）时
    抢救已经完整的那几项：从后往前找最后一个完整对象的 ``}``，补上 ``]``。"""
    body = str(text or "")
    fenced = _FENCE_RE.search(body)
    if fenced:
        body = fenced.group(1)
    elif body.lstrip().startswith("```"):
        body = body.lstrip()[3:]
        body = body[4:] if body.lower().startswith("json") else body
    start = body.find("[")
    if start < 0:
        return None
    end = body.rfind("]")
    if end > start:
        try:
            data = json.loads(body[start:end + 1])
            return data if isinstance(data, list) else None
        except ValueError:
            pass
    return _salvage(body[start:])


def _salvage(body: str):
    """``[ {...}, {...}, {截断`` → 逐个 ``}`` 往回试，直到补 ``]`` 能解析。"""
    cut = len(body)
    while True:
        cut = body.rfind("}", 0, cut)
        if cut <= 0:
            return None
        try:
            data = json.loads(body[:cut + 1].rstrip().rstrip(",") + "]")
        except ValueError:
            continue
        return data if isinstance(data, list) and data else None


def parse_proposals(text: str, *, projects: Iterable[str] = (), run_at: str = "") -> list[Proposal]:
    """解析模型输出；不合法的项丢掉。``projects`` 是本次候选涉及的 cwd：模型写的项目名对回完整路径。"""
    data = _json_array(text)
    if data is None:
        return []
    cwds = {md.posix_home_label(p).lower(): p for p in projects}
    cwds.update({p.lower(): p for p in projects})
    out: list[Proposal] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "add").strip().lower()
        scope = str(item.get("scope") or "global").strip().lower()
        kind = str(item.get("type") or "feedback").strip().lower()
        title = " ".join(str(item.get("title") or "").split())
        if action not in ACTIONS or scope not in SCOPES or not title:
            continue
        project = str(item.get("project") or "").strip()
        if scope == "project":
            project = cwds.get(project.lower(), project)
            if not project:
                scope = "global"
        else:
            project = ""
        evidence = item.get("evidence")
        evidence = [str(e).strip() for e in evidence if str(e).strip()] if isinstance(evidence, list) else (
            [str(evidence).strip()] if evidence else [])
        pid = proposal_id(action, scope, project, title)
        if pid in seen:
            continue
        seen.add(pid)
        out.append(Proposal(id=pid, action=action, scope=scope, project=project, type=kind if kind in TYPES else "feedback",
                            title=title, why=str(item.get("why") or "").strip(), how=str(item.get("how") or "").strip(),
                            evidence=evidence, replaces=" ".join(str(item.get("replaces") or "").split()), run_at=run_at))
    return out


class ProposalStore:
    """``<root>/proposals.json``：所有提案（含审过的）。拒掉的标题就是「别再提」名单。"""

    def __init__(self, root: Path | str) -> None:
        self.path = Path(root) / PROPOSALS_FILE

    def load(self) -> list[Proposal]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items = data.get("items") if isinstance(data, dict) else data
        return [Proposal.from_dict(i) for i in items if isinstance(i, dict)] if isinstance(items, list) else []

    def save(self, items: Iterable[Proposal]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"items": [p.to_dict() for p in items]}, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def add(self, proposals: Iterable[Proposal]) -> int:
        """并入新提案：和已有（任何状态）同 id 的不重复；返回真正新增的条数。"""
        items = self.load()
        known = {p.id for p in items}
        added = 0
        for proposal in proposals:
            if proposal.id in known:
                continue
            items.append(proposal)
            known.add(proposal.id)
            added += 1
        if added:
            self.save(items)
        return added

    def pending(self) -> list[Proposal]:
        return [p for p in self.load() if p.status == STATUS_PENDING]

    def get(self, pid: str) -> Proposal | None:
        return next((p for p in self.load() if p.id == pid), None)

    def update(self, proposal: Proposal) -> None:
        items = self.load()
        for index, item in enumerate(items):
            if item.id == proposal.id:
                items[index] = proposal
                break
        else:
            items.append(proposal)
        self.save(items)

    def dismissed_titles(self) -> list[str]:
        return [p.title for p in self.load() if p.status == STATUS_REJECTED]

    def counts(self) -> dict:
        items = self.load()
        return {status: sum(1 for p in items if p.status == status) for status in STATUSES} | {"total": len(items)}


# ---------------------------------------------------------------- 跑一次


@dataclass
class RunResult:
    ok: bool = False
    error: str = ""
    candidates: int = 0
    proposals: int = 0            # 模型给的
    added: int = 0                # 并入提案库后真正新增的
    model: str = ""
    effort: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0
    run_at: str = ""
    newest_candidate: str = ""
    raw_text: str = ""
    truncated: bool = False       # 输出到了 max_tokens，只抢救到了前面几条


def build_prompt(settings: dict, rows: list[dict], memory: str, dismissed: Iterable[str], language: str | None = None) -> str:
    template = md.prompt_template(settings, language)
    dismissed_text = "\n".join(f"- {t}" for t in dismissed) or "(无)"
    return wb.render_template(template, candidates=format_candidates(rows) or "(无)", memory=memory or "(无)",
                              dismissed=dismissed_text)


def run_once(now: dt.datetime, settings: dict, rows: list[dict], state: dict, provider, *,
             store: ProposalStore, complete: Callable, memory: str | None = None, home: Path | None = None,
             entries_text: str = "", clock: Callable[[], float] | None = None) -> tuple[RunResult, dict]:
    """阻塞：挑候选 → 拼提示词 → 调模型 → 解析 → 并入提案库。返回 (结果, 新状态)。任何失败折成 ok=False。"""
    import time

    clock = clock or time.monotonic
    run_at = now.isoformat(timespec="seconds")
    result = RunResult(run_at=run_at)
    picked, newest = select_candidates(rows, state)
    result.candidates = len(picked)
    result.newest_candidate = newest
    new_state = mark_attempt(state, now)
    if not picked:
        result.ok = True
        new_state = {**new_state, "done_date": now.date().isoformat(), "last_run_at": run_at, "last_error": "",
                     "last_result": {"candidates": 0, "proposals": 0, "added": 0}}
        return result, new_state
    model = str(settings.get("model") or "") or str(getattr(provider, "model", "") or "")
    effort = str(settings.get("effort") or "") or str(getattr(provider, "effort", "") or "")
    result.model, result.effort = model, effort
    projects = sorted({repo_root(str(r.get("project") or "")) for r in picked if r.get("project")})
    if memory is None:
        memory = memory_context(picked, home=home, entries_text=entries_text)
    prompt = build_prompt(settings, picked, memory, store.dismissed_titles())
    started = clock()
    try:
        completion = complete(prompt, "", provider, model=model, effort=effort, timeout=TIMEOUT_S, max_tokens=MAX_TOKENS)
    except Exception as exc:  # noqa: BLE001 - ProviderError 和别的都折成失败原因
        result.seconds = round(clock() - started, 1)
        result.error = str(exc) or type(exc).__name__
        return result, {**new_state, "last_error": result.error}
    result.seconds = round(clock() - started, 1)
    result.model = str(getattr(completion, "model", "") or model)
    result.tokens_in = int(getattr(completion, "input_tokens", 0) or 0)
    result.tokens_out = int(getattr(completion, "output_tokens", 0) or 0)
    result.raw_text = str(getattr(completion, "text", "") or "")
    proposals = parse_proposals(result.raw_text, projects=projects, run_at=run_at)
    if _json_array(result.raw_text) is None:
        result.error = "模型没有按约定输出 JSON 数组"
        return result, {**new_state, "last_error": result.error}
    stop = str(getattr(completion, "stop_reason", "") or "")
    if stop == "max_tokens":
        result.truncated = True
    result.proposals = len(proposals)
    result.added = store.add(proposals)
    result.ok = True
    new_state = {**new_state, "done_date": now.date().isoformat(), "last_run_at": run_at, "last_error": "",
                 "last_candidate_time": newest,
                 "last_result": {"candidates": result.candidates, "proposals": result.proposals, "added": result.added,
                                 "model": result.model, "effort": result.effort, "tokens_in": result.tokens_in,
                                 "tokens_out": result.tokens_out, "seconds": result.seconds}}
    return result, new_state
