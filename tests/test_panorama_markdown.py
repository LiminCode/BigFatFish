# -*- coding: utf-8 -*-
"""简报页的 Markdown 渲染（``pet/panorama/markdown.py``）：只认简报会写出来的子集，别的全是文字。

守住的：标题 / 列表 / 段落的结构；★ 与 bug 记号变成类名（原来是 Qt 窗口里 ``_decorate`` 做的上色）；
链接只认 http(s) 且在新标签页开；任何像标记的东西（``<script>``、``javascript:`` 地址）都只是几个字。
"""
from __future__ import annotations

import re

from pet import work_briefing as wb
from pet.panorama import markdown as md


def test_headings_lists_and_paragraphs_keep_their_structure():
    out = md.render("## Jira\n读不到。\n\n**等我评审**\n- 第一条\n- 第二条\n\n1. 先做这个\n2. 再做那个\n")
    assert out.startswith("<h3>Jira</h3>\n<p>读不到。</p>\n<p><strong>等我评审</strong></p>\n<ul>\n<li>第一条</li>\n<li>第二条</li>\n</ul>")
    assert out.endswith("<ol>\n<li>先做这个</li>\n<li>再做那个</li>\n</ol>")


def test_stars_at_the_head_of_an_item_become_a_class_by_count():
    out = md.render("- ★★★ 最急\n- ★★ 一般\n- ★ 知悉\n- 没有星")
    assert '<li><span class="star s3">★★★</span> 最急</li>' in out
    assert '<li><span class="star s2">★★</span> 一般</li>' in out and '<li><span class="star s1">★</span> 知悉</li>' in out
    assert "<li>没有星</li>" in out


def test_a_bug_row_and_its_indented_scene_lines_are_one_tinted_item():
    text = f"- ★★ {wb.BUG_MARK} DEMO-9 登录崩\n  - 场景：点两下\n  - 影响：所有人\n- ★ 别的"
    out = md.render(text, bug_mark=wb.BUG_MARK)
    assert out == ('<ul>\n<li class="bug"><span class="star s2">★★</span> ' + wb.BUG_MARK + " DEMO-9 登录崩\n<ul>\n"
                   "<li>场景：点两下</li>\n<li>影响：所有人</li>\n</ul>\n</li>\n"
                   '<li><span class="star s1">★</span> 别的</li>\n</ul>')


def test_inline_code_becomes_a_chip_and_bold_is_bold():
    out = md.render("- [DEMO-1](https://x.example/browse/DEMO-1) `进行中` **今天**")
    assert '<code class="chip">进行中</code>' in out and "<strong>今天</strong>" in out


def test_links_open_in_a_new_tab_and_only_http_counts():
    out = md.render("看 [工单](https://x.example/browse/A-1?x=1&y=2) 和 [坏的](javascript:alert(1)) 和 https://bare.example/p. 完")
    assert '<a href="https://x.example/browse/A-1?x=1&amp;y=2" target="_blank" rel="noopener noreferrer">工单</a>' in out
    assert "javascript:" in out and "<a href=\"javascript" not in out, "不是 http(s) 的地址只是几个字"
    assert '<a href="https://bare.example/p" target="_blank" rel="noopener noreferrer">https://bare.example/p</a>.' in out


def test_everything_that_looks_like_markup_is_text():
    out = md.render("<script>alert(1)</script> 与 <b>粗</b>\n- <img src=x onerror=alert(1)>")
    assert "<script" not in out and "<b>" not in out and "<img" not in out
    assert "&lt;script&gt;" in out and "&lt;img src=x onerror=alert(1)&gt;" in out
    assert not re.search(r"<\w+[^>]*\son\w+=", out), "没有任何真的带事件属性的标签"


def test_code_spans_are_not_linked_or_bolded_inside():
    out = md.render("`https://in.code/** no **` 外面 **是**")
    assert '<code class="chip">https://in.code/** no **</code>' in out and "<strong>是</strong>" in out
    assert out.count("<a ") == 0


def test_nested_lists_close_in_order_and_paragraph_after_list_starts_fresh():
    out = md.render("- 一\n  - 一甲\n    - 一甲子\n- 二\n\n收尾一句")
    assert out == "<ul>\n<li>一\n<ul>\n<li>一甲\n<ul>\n<li>一甲子</li>\n</ul>\n</li>\n</ul>\n</li>\n<li>二</li>\n</ul>\n<p>收尾一句</p>"


def test_empty_and_plain_text():
    assert md.render("") == "" and md.render("   \n") == ""
    assert md.render("就一句话") == "<p>就一句话</p>"
