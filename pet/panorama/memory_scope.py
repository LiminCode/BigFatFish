# -*- coding: utf-8 -*-
"""记忆按作用域列出，并标出重复的和像是放错了作用域的。

作用域是**它放在哪**决定的，三层：

- 机器（账号）：这台 Windows 上个人的 Claude Code，WSL 里公司的 Claude Code；
- 全局：那个家目录的 ``CLAUDE.md``——对所有项目生效（受管块里的每条规矩算一条）；
- 项目：``~/.claude/projects/<项目>/memory/`` 里的每个文件，只对那个项目生效。

判定只靠**字面相同**：标题一样（不分大小写、不看标点和空白），或者说明一样（太短的说明不比）。这样判不出
「换了个说法的同一件事」，那要靠模型去读；这里只做便宜、确定、不会冤枉人的那一半。

- ``dup``：同一台机器上还有一条和它一样的；
- ``to_global``：同一条出现在这台机器的两个以上项目里——像是全局规矩，却按项目各记了一份；
- ``in_global``：这台机器的全局规矩里已经有它了，项目里这份多余；
- ``both_sides``：另一台机器上也有。这不算放错：个人和公司各自需要一份，只是告诉你两边都有。

纯函数：不读盘、不认界面语言。输入是 ``claude_home_probe.memory_index`` 的结果，文字由 ``sources`` 去配。
"""
from __future__ import annotations

import re

FLAGS = ("dup", "to_global", "in_global", "both_sides")     # 也是显示顺序
MISPLACED = ("to_global", "in_global")
MIN_DESCRIPTION = 12        # 归一化后比这短的说明不拿来比：撞上的多半是巧合

_HOME_PREFIX = re.compile(r"^(?:[A-Za-z]--Users-[^-]+-|-home-[^-]+-|-mnt-[a-z]-Users-[^-]+-)")


def project_label(name: str) -> str:
    """项目目录名是绝对路径编码出来的（``C--Users-dev-Github-tomato``）：去掉家目录那一截再显示。"""
    return _HOME_PREFIX.sub("", name or "") or (name or "")


def _key(text: str) -> str:
    return re.sub(r"[\W_]+", "", str(text or "").lower())


def analyse(sides: list[tuple[str, dict | None]]) -> dict:
    """``[(机器标识, 记忆索引)]`` → 每台机器一段：全局规矩、你自己写的小节、各项目的记忆，每条带 ``flags`` 和 ``twins``。"""
    items: list[dict] = []          # 所有参与比对的条目：全局规矩和项目记忆摊平
    out = {"sides": []}
    for side_id, index in sides:
        index = index or {}
        rules = [{"title": str(rule.get("title") or ""), "text": str(rule.get("text") or "")} for rule in index.get("rules") or []]
        projects = []
        for project in index.get("projects") or []:
            name = str(project.get("name") or "")
            entries = [{"file": str(e.get("file") or ""), "name": str(e.get("name") or ""), "description": str(e.get("description") or ""),
                        "type": str(e.get("type") or ""), "bytes": e.get("bytes", 0), "mtime": str(e.get("mtime") or "")}
                       for e in project.get("entries") or []]
            projects.append({"name": name, "label": project_label(name), "entries": entries})
            items += [{"side": side_id, "project": project_label(name), "scope": name, "title": e["name"],
                       "description": e["description"], "row": e} for e in entries]
        items += [{"side": side_id, "project": "", "scope": "", "title": rule["title"], "description": "", "row": rule} for rule in rules]
        out["sides"].append({"id": side_id, "rules": rules, "sections": [str(s) for s in index.get("sections") or []],
                             "projects": projects, "truncated": bool(index.get("truncated"))})

    groups: dict[tuple[str, str], list[dict]] = {}
    for item in items:
        title, description = _key(item["title"]), _key(item["description"])
        if title:
            groups.setdefault(("title", title), []).append(item)
        if len(description) >= MIN_DESCRIPTION:
            groups.setdefault(("description", description), []).append(item)
    twins: dict[int, list[dict]] = {}
    for members in groups.values():
        for item in members:
            mine = twins.setdefault(id(item), [])
            mine += [other for other in members if other is not item and other not in mine]

    for item in items:
        others = twins.get(id(item), [])
        same_side = [o for o in others if o["side"] == item["side"]]
        found = set()
        if same_side:
            found.add("dup")
        if any(o["side"] != item["side"] for o in others):
            found.add("both_sides")
        if item["scope"]:                                   # 只有项目里的记忆才谈得上放错作用域
            if any(o["scope"] and o["scope"] != item["scope"] for o in same_side):
                found.add("to_global")
            if any(not o["scope"] for o in same_side):
                found.add("in_global")
        item["row"]["flags"] = [flag for flag in FLAGS if flag in found]
        item["row"]["twins"] = [{"side": o["side"], "project": o["project"], "title": o["title"]} for o in others]

    for side in out["sides"]:
        entries = [e for project in side["projects"] for e in project["entries"]]
        side["counts"] = {"entries": len(entries), "dup": sum("dup" in e["flags"] for e in entries),
                          "misplaced": sum(any(flag in MISPLACED for flag in e["flags"]) for e in entries)}
    return out
