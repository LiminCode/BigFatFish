# -*- coding: utf-8 -*-
"""随手记笔记的复习（零 Qt）：读笔记的 review 字段、挑到期的、按回答换档、只改那一行。

纪律：不起 git、不调模型；样例文字中性。
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from pet import capture_organize as co
from pet import capture_review as cr

TODAY = dt.date(2026, 11, 26)


def _note(root: Path, name: str, *, review: str = "{next: 2026-11-26, interval: 1, count: 0, lapses: 0}", title: str = "",
          kind: str = "post", source: str = "https://example.com/p") -> str:
    path = root / co.NOTES_DIR / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    review_line = f"review: {review}\n" if review else ""
    path.write_text(f"---\ntitle: {title or name}\ntags: [reading, habits]\nkind: {kind}\nsource: {source}\ncaptured: 2026-11-25 09:00\n"
                    f"via: fish\n{review_line}---\n\n<!-- by Claude, 2026-11-25 -->\n\n## 原文存档\nThe original **text**.\n\n"
                    f"## 要点\n- point one\n- point two\n\n## 我的话\nSmall habits ride on old ones.\n\n## 关联\n- [[x]]\n", encoding="utf-8")
    return f"{co.NOTES_DIR}/{name}.md"


def test_reads_the_review_field_in_both_yaml_shapes(tmp_path):
    flow = _note(tmp_path, "a")
    block = _note(tmp_path, "b", review="\n  next: 2026-11-20\n  interval: 7\n  count: 3\n  lapses: 1")
    _note(tmp_path, "c", review="")                                   # 没有 review 的不算复习笔记
    (tmp_path / co.NOTES_DIR / "README.md").write_text("---\nreview: {next: 2000-01-01}\n---\n", encoding="utf-8")
    notes = {note.path: note for note in cr.notes(tmp_path)}
    assert set(notes) == {flow, block}
    a, b = notes[flow], notes[block]
    assert (a.next, a.interval, a.count, a.lapses) == (dt.date(2026, 11, 26), 1, 0, 0)
    assert (b.next, b.interval, b.count, b.lapses) == (dt.date(2026, 11, 20), 7, 3, 1)
    assert a.title == "a" and a.kind == "post" and a.source == "https://example.com/p" and a.captured == "2026-11-25 09:00"
    assert a.points == "- point one\n- point two" and a.words == "Small habits ride on old ones."
    assert cr.notes(tmp_path / "nowhere") == []


def test_due_picks_most_lapses_first_then_the_oldest_and_counts_the_rest(tmp_path):
    for name, review in (("fresh", "{next: 2026-11-26, interval: 1, count: 0, lapses: 0}"),
                         ("old", "{next: 2026-11-01, interval: 3, count: 2, lapses: 0}"),
                         ("forgotten", "{next: 2026-11-25, interval: 1, count: 4, lapses: 2}"),
                         ("later", "{next: 2026-12-01, interval: 7, count: 1, lapses: 0}"),
                         ("older", "{next: 2026-10-01, interval: 3, count: 2, lapses: 0}")):
        _note(tmp_path, name, review=review)
    batch, total = cr.due(cr.notes(tmp_path), TODAY, limit=3)
    assert [Path(n.path).stem for n in batch] == ["forgotten", "older", "old"] and total == 4
    assert cr.next_due(cr.notes(tmp_path), TODAY) == dt.date(2026, 12, 1)
    assert cr.next_due([], TODAY) is None


@pytest.mark.parametrize(("interval", "answer", "expected"), [
    (1, "remember", (3, 1, 0)), (14, "remember", (30, 1, 0)), (180, "remember", (180, 1, 0)), (5, "remember", (7, 1, 0)),
    (7, "fuzzy", (7, 1, 0)), (30, "forgot", (1, 1, 1))])
def test_grading_follows_the_ladder(interval, answer, expected):
    review = cr.grade({"next": TODAY, "interval": interval, "count": 0, "lapses": 0}, answer, TODAY)
    assert (review["interval"], review["count"], review["lapses"]) == expected
    assert review["next"] == TODAY + dt.timedelta(days=expected[0])
    with pytest.raises(ValueError):
        cr.grade({"interval": 1}, "maybe", TODAY)


def test_write_grade_changes_only_the_review_line(tmp_path):
    path = _note(tmp_path, "a", review="{next: 2026-11-26, interval: 3, count: 2, lapses: 1}")
    before = (tmp_path / path).read_text(encoding="utf-8")
    review = cr.write_grade(tmp_path, path, "remember", TODAY)
    after = (tmp_path / path).read_text(encoding="utf-8")
    assert review == {"next": dt.date(2026, 12, 3), "interval": 7, "count": 3, "lapses": 1}
    assert after == before.replace("review: {next: 2026-11-26, interval: 3, count: 2, lapses: 1}",
                                   "review: {next: 2026-12-03, interval: 7, count: 3, lapses: 1}")
    block = _note(tmp_path, "b", review="\n  next: 2026-11-20\n  interval: 7\n  count: 3\n  lapses: 1")
    cr.write_grade(tmp_path, block, "forgot", TODAY)
    text = (tmp_path / block).read_text(encoding="utf-8")
    assert "review: {next: 2026-11-27, interval: 1, count: 4, lapses: 2}\n---" in text and "  interval: 7" not in text


def test_write_grade_refuses_paths_outside_the_notes_and_notes_without_review(tmp_path):
    _note(tmp_path, "plain", review="")
    (tmp_path / "secret.md").write_text("---\nreview: {next: 2026-11-26, interval: 1, count: 0, lapses: 0}\n---\n", encoding="utf-8")
    for bad in (f"{co.NOTES_DIR}/plain.md", "secret.md", f"{co.NOTES_DIR}/../../secret.md", f"{co.NOTES_DIR}/missing.md"):
        with pytest.raises(cr.ReviewError):
            cr.write_grade(tmp_path, bad, "remember", TODAY)


def test_the_round_state_remembers_what_waits_for_a_push_and_how_many_were_done_today(tmp_path):
    state = cr.load_state(tmp_path)
    assert state == {"date": "", "done": 0, "pending": []}
    state = cr.note_graded(tmp_path, "9-Learning/Notes/a.md", TODAY)
    state = cr.note_graded(tmp_path, "9-Learning/Notes/a.md", TODAY)
    state = cr.note_graded(tmp_path, "9-Learning/Notes/b.md", TODAY)
    assert state == {"date": "2026-11-26", "done": 3, "pending": ["9-Learning/Notes/a.md", "9-Learning/Notes/b.md"]}
    assert cr.load_state(tmp_path) == state
    assert cr.note_graded(tmp_path, "9-Learning/Notes/c.md", TODAY + dt.timedelta(days=1))["done"] == 1, "新的一天从头数"
    assert cr.note_pushed(tmp_path, ["9-Learning/Notes/a.md"])["pending"] == ["9-Learning/Notes/b.md", "9-Learning/Notes/c.md"]
    assert cr.commit_message(["9-Learning/Notes/a.md", "9-Learning/Notes/b.md"]) == "Review: 2 notes\n\n9-Learning/Notes/a.md\n9-Learning/Notes/b.md"
    assert cr.commit_message(["9-Learning/Notes/a.md"]).startswith("Review: 1 note\n")
