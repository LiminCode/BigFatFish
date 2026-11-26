# -*- coding: utf-8 -*-
"""随手记笔记的复习（零 Qt、不调模型、不碰 git）：读 ``9-Learning/Notes/`` 里每条笔记的 ``review`` 字段、挑出今天到期的、
按「记得 / 模糊 / 忘了」换档、只改那一行。决定见 ADR 0021，规矩在用户私有库的 ``9-Learning/Notes/README.md``「复习」一节：

- **到期** = ``review.next`` ≤ 今天；一轮最多 N 条，先挑 ``lapses`` 多的，再挑 ``next`` 早的；
- 间隔档位 1 → 3 → 7 → 14 → 30 → 90 → 180 天：记得 = 进一档（180 封顶）；模糊 = 原档；忘了 = 回到 1、``lapses + 1``；
  三种都 ``count + 1``；``next`` = 今天 + 新间隔。

**状态只在笔记自己的 frontmatter 里**：手机上的 Claude 复习过，电脑这边拉一次就知道；这里写回时只换 ``review`` 那一行
（块写法的几行换成一行流式写法），别的一个字不动。

一轮改完一起提交（``Review: N notes``）。打完分到推上去之间可能隔几分钟、肥鱼也可能被关掉，所以「哪几条还没推」记在本机的
``capture-review.json``（连同今天复习了几条），下次启动接着推。丢了不要紧：改动还在克隆里，下一次任何推送前的 pull 会 autostash。
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import capture_inbox as ci
from . import capture_organize as co

LADDER = (1, 3, 7, 14, 30, 90, 180)
ANSWERS = ("remember", "fuzzy", "forgot")
DEFAULT_BATCH = 5
STATE_FILE = "capture-review.json"
_FIELDS = ("next", "interval", "count", "lapses")
_FLOW_RE = re.compile(r"^review:\s*\{(.*)\}\s*$")
_PAIR_RE = re.compile(r"\s*([A-Za-z_]+)\s*:\s*([^,]*)")
_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")


class ReviewError(ValueError):
    """这条不能打分：不在笔记目录里、文件不在、没有 review 字段。"""


@dataclass
class ReviewNote:
    path: str                 # 相对仓库，正斜杠
    title: str
    kind: str
    source: str
    captured: str
    next: dt.date
    interval: int
    count: int
    lapses: int
    points: str               # 「要点」那一段的 Markdown
    words: str                # 「我的话」那一段的 Markdown


# ───────────────────────── 读 ─────────────────────────

def _int(value, default: int = 0) -> int:
    try:
        return max(0, int(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _date(value) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value).strip().strip("'\""))
    except ValueError:
        return None


def _review_span(lines: list[str]) -> tuple[int, int, dict] | None:
    """frontmatter 里 ``review`` 占的行（起、止不含）和读出来的字典；没有回 ``None``。两种写法：一行流式 / 缩进块。"""
    for index, line in enumerate(lines):
        if not line.startswith("review:"):
            continue
        flow = _FLOW_RE.match(line)
        if flow:
            return index, index + 1, {key: value.strip() for key, value in _PAIR_RE.findall(flow.group(1))}
        if line[len("review:"):].strip():
            return None
        end, raw = index + 1, {}
        while end < len(lines) and lines[end].startswith((" ", "\t")):
            key, _, value = lines[end].strip().partition(":")
            raw[key.strip()] = value.strip()
            end += 1
        return index, end, raw
    return None


def _state(raw: dict) -> dict | None:
    when = _date(raw.get("next", ""))
    if when is None:
        return None
    return {"next": when, "interval": _int(raw.get("interval"), 1) or 1, "count": _int(raw.get("count")), "lapses": _int(raw.get("lapses"))}


def _section(body: str, heading: str) -> str:
    out, inside = [], False
    for line in body.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            inside = match.group(1) == heading
            continue
        if inside:
            out.append(line)
    return "\n".join(out).strip()


def read_note(root: Path, path: Path) -> ReviewNote | None:
    text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    front = co._split_front(text)
    if front is None:
        return None
    lines, body = front
    span = _review_span(lines)
    state = _state(span[2]) if span else None
    if state is None:
        return None
    return ReviewNote(path.relative_to(root).as_posix(), co._field(lines, "title") or path.stem, co._field(lines, "kind"),
                      co._field(lines, "source"), co._field(lines, "captured"), state["next"], state["interval"], state["count"],
                      state["lapses"], _section(body, "要点"), _section(body, "我的话"))


def notes(repo_dir: str | Path) -> list[ReviewNote]:
    """笔记目录里所有带 ``review`` 的笔记（README 不算）。目录不在就是空。"""
    root = Path(repo_dir)
    try:
        paths = sorted(p for p in (root / co.NOTES_DIR).iterdir() if p.is_file() and p.suffix.lower() == ".md" and p.name.lower() != "readme.md")
    except OSError:
        return []
    out = []
    for path in paths:
        try:
            note = read_note(root, path)
        except OSError:
            continue
        if note is not None:
            out.append(note)
    return out


def due(items: list[ReviewNote], today: dt.date, *, limit: int = DEFAULT_BATCH) -> tuple[list[ReviewNote], int]:
    """今天这一轮（最多 ``limit`` 条：``lapses`` 多的在前，再按 ``next`` 早的）和一共到期几条。"""
    ready = sorted((n for n in items if n.next <= today), key=lambda n: (-n.lapses, n.next, n.path))
    return ready[:max(1, int(limit))], len(ready)


def next_due(items: list[ReviewNote], today: dt.date) -> dt.date | None:
    """今天之后最早到期的那天（页面「今天没有了，下一条在 …」）。"""
    later = [n.next for n in items if n.next > today]
    return min(later) if later else None


# ───────────────────────── 打分 ─────────────────────────

def grade(review: dict, answer: str, today: dt.date) -> dict:
    """按规矩的表换档；回新的 ``{next, interval, count, lapses}``。"""
    if answer not in ANSWERS:
        raise ValueError(answer)
    interval, count, lapses = _int(review.get("interval"), 1) or 1, _int(review.get("count")), _int(review.get("lapses"))
    if answer == "remember":
        interval = next((step for step in LADDER if step > interval), LADDER[-1])
    elif answer == "forgot":
        interval, lapses = LADDER[0], lapses + 1
    return {"next": today + dt.timedelta(days=interval), "interval": interval, "count": count + 1, "lapses": lapses}


def _line(review: dict) -> str:
    return (f"review: {{next: {review['next'].isoformat()}, interval: {review['interval']}, count: {review['count']}, "
            f"lapses: {review['lapses']}}}")


def write_grade(repo_dir: str | Path, rel_path: str, answer: str, today: dt.date) -> dict:
    """给一条笔记打分：只换 frontmatter 里 ``review`` 那几行，原子写回。不在笔记目录、文件不在、没有 review 抛 ``ReviewError``。"""
    root = Path(repo_dir)
    notes_dir = (root / co.NOTES_DIR).resolve()
    target = (root / str(rel_path)).resolve()
    if target.parent != notes_dir or target.suffix.lower() != ".md" or target.name.lower() == "readme.md":
        raise ReviewError("outside")
    try:
        raw = target.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReviewError("missing") from exc
    newline = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")
    front = co._split_front(text)
    span = _review_span(front[0]) if front else None
    state = _state(span[2]) if span else None
    if state is None:
        raise ReviewError("no_review")
    review = grade(state, answer, today)
    lines = front[0]
    lines[span[0]:span[1]] = [_line(review)]
    head_end = text.find("\n---", 3)
    updated = "---\n" + "\n".join(lines) + text[head_end:]
    ci._write(target, updated.replace("\n", newline).encode("utf-8"))
    return review


# ───────────────────────── 本机：还没推的几条、今天复习了几条 ─────────────────────────

def load_state(config_dir: str | Path) -> dict:
    try:
        data = json.loads((Path(config_dir) / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    pending = data.get("pending")
    return {"date": str(data.get("date") or ""), "done": _int(data.get("done")),
            "pending": [str(p) for p in pending] if isinstance(pending, list) else []}


def _save(config_dir: str | Path, state: dict) -> dict:
    path = Path(config_dir) / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    ci._write(path, json.dumps(state, ensure_ascii=False, indent=1).encode("utf-8"))
    return state


def note_graded(config_dir: str | Path, rel_path: str, today: dt.date) -> dict:
    state = load_state(config_dir)
    day = today.isoformat()
    state["done"] = state["done"] + 1 if state["date"] == day else 1
    state["date"] = day
    if rel_path not in state["pending"]:
        state["pending"].append(rel_path)
    return _save(config_dir, state)


def note_pushed(config_dir: str | Path, paths: list[str]) -> dict:
    state = load_state(config_dir)
    state["pending"] = [p for p in state["pending"] if p not in set(paths)]
    return _save(config_dir, state)


def done_today(config_dir: str | Path, today: dt.date) -> int:
    state = load_state(config_dir)
    return state["done"] if state["date"] == today.isoformat() else 0


def commit_message(paths: list[str]) -> str:
    """照规矩：``Review: N notes``；正文列出这一轮改了哪几条。"""
    return f"Review: {len(paths)} note{'s' if len(paths) != 1 else ''}\n\n" + "\n".join(paths)
