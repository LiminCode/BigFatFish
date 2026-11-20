# -*- coding: utf-8 -*-
"""简报那一小块 Markdown → HTML。**只用标准库、不碰 Qt。**

只认简报（工作简报、个人简报）会写出来的子集，其余一律当文字转义后原样显示：

- 块：``#`` 标题（``##`` → ``<h3>``，只是比页面标题低一级）、``-`` / ``*`` 无序列表、``1.`` 有序列表（两个空格缩进
  一级，可嵌套）、空行隔开的段落；
- 行内：``**粗体**``、``` `行内代码` ``` → 小标签（``<code class="chip">``，简报里是工单状态）、``[文字](https://…)``
  和裸的 ``https://…`` → 新标签页打开的链接；只认 ``http(s)://``，别的协议只是几个字；
- 简报自己的记号：列表项开头的 ``★`` 按星数打类（``star s1`` / ``s2`` / ``s3``，★★★ 最醒目）；开头是 bug 记号
  （``work_briefing.BUG_MARK``）的列表项打 ``bug`` 类，它下面缩进的场景行是它的子列表，底色随它。

这些上色规则在 Qt 窗口里是 ``WorkBriefingWindow._decorate`` 遍历文本片段做的；这里改成渲染时打类名，样式在
``page/report.css``。产出的 HTML 里除了这几个标签和类名没有别的：文字全部经 ``escape``，链接地址也转义过。
"""
from __future__ import annotations

import html
import re

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_ITEM = re.compile(r"^(\s*)(?:([-*])|(\d{1,3})[.)])\s+(.*)$")
_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_BARE_URL = re.compile(r"(?<![\w\"'=/(])https?://[^\s<>()\"']+")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_STARS = re.compile(r"^(★{1,3})\s*")
_HOLD = "\x00%d\x00"
_HOLD_RE = re.compile("\x00(\\d+)\x00")

INDENT = 2          # 列表嵌套：每级两个空格（制表符算一级）


def render(text: str, *, bug_mark: str = "") -> str:
    """整段 Markdown → HTML 片段（没有外层容器）。空文本给空串。"""
    out: list[str] = []
    paragraph: list[str] = []
    lists: list[tuple[int, str]] = []       # 打开着的列表：(缩进级别, "ul" / "ol")，最里面的在最后
    item_open = False                        # 最里面那个列表里有一个 <li> 还没关（嵌套列表要放进它里面）

    def flush_paragraph() -> None:
        if paragraph:
            out.append("<p>" + "\n".join(paragraph) + "</p>")
            paragraph.clear()

    def close_item() -> None:
        nonlocal item_open
        if out[-1].startswith("<li"):
            out[-1] += "</li>"               # 没有子列表的项：开合在同一行
        else:
            out.append("</li>")
        item_open = False

    def close_lists(down_to: int) -> None:
        nonlocal item_open
        while lists and lists[-1][0] >= down_to:
            if item_open:
                close_item()
            out.append(f"</{lists.pop()[1]}>")
            item_open = bool(lists)          # 回到外层：外层那一项还开着

    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            flush_paragraph()
            if not lists:
                continue
            continue                         # 列表中间的空行不算结束：下一行决定
        heading = _HEADING.match(line)
        if heading is not None:
            flush_paragraph()
            close_lists(0)
            level = min(len(heading.group(1)) + 1, 6)
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        item = _ITEM.match(line)
        if item is not None:
            flush_paragraph()
            indent = item.group(1).replace("\t", " " * INDENT)
            level = len(indent) // INDENT
            tag = "ul" if item.group(2) else "ol"
            if lists and level > lists[-1][0]:
                lists.append((level, tag))
                out.append(f"<{tag}>")
            else:
                close_lists(level + 1)
                if lists and lists[-1][0] == level and lists[-1][1] != tag:
                    close_lists(level)
                if not lists or lists[-1][0] < level:
                    lists.append((level, tag))
                    out.append(f"<{tag}>")
                elif item_open:
                    close_item()
            body, classes = item.group(4), []
            stars = _STARS.match(body)
            if stars is not None:
                body = body[stars.end():]
                star_html = f'<span class="star s{len(stars.group(1))}">{stars.group(1)}</span> '
            else:
                star_html = ""
            if bug_mark and body.startswith(bug_mark):
                classes.append("bug")
            attr = f' class="{" ".join(classes)}"' if classes else ""
            out.append(f"<li{attr}>{star_html}{_inline(body)}")
            item_open = True
            continue
        if lists and raw.startswith(" " * INDENT * (lists[-1][0] + 1)) and item_open:
            out[-1] += "\n" + _inline(line.strip())     # 列表项的续行
            continue
        close_lists(0)
        paragraph.append(_inline(line.strip()))
    flush_paragraph()
    close_lists(0)
    return "\n".join(out)


def _inline(text: str) -> str:
    """行内：先把代码和链接摘出来占位（里面的东西不再被别的规则碰），转义，再放回去。"""
    held: list[str] = []

    def hold(piece: str) -> str:
        held.append(piece)
        return _HOLD % (len(held) - 1)

    def code(match: re.Match) -> str:
        return hold(f'<code class="chip">{html.escape(match.group(1))}</code>')

    def link(match: re.Match) -> str:
        return hold(_anchor(match.group(2), _inline(match.group(1))))

    def bare(match: re.Match) -> str:
        url = match.group(0).rstrip(".,;:!?，。；：")
        return hold(_anchor(url, html.escape(url))) + html.escape(match.group(0)[len(url):])

    text = _CODE.sub(code, text)
    text = _LINK.sub(link, text)
    text = _BARE_URL.sub(bare, text)
    text = html.escape(text, quote=False)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    return _HOLD_RE.sub(lambda m: held[int(m.group(1))], text)


def _anchor(url: str, inner: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{inner}</a>'
