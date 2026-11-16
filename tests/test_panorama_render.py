# -*- coding: utf-8 -*-
"""配置全景：图 → 离线快照（自带数据的 HTML 文件），以及本机服务发的外壳、静态文件和数据。"""
from __future__ import annotations

import json
import re

import pytest

from pet import i18n
from pet.panorama import render, sources
from tests import panorama_samples as samples

CJK = re.compile(r"[一-鿿]")
DATA_LINE = f"const {render.DATA_NAME} = "


@pytest.fixture(autouse=True)
def _chinese():
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


def _embedded(page: str) -> dict:
    line = next(l for l in page.splitlines() if l.startswith(DATA_LINE))
    return json.loads(line[len(DATA_LINE):].rstrip(";").replace("<\\/", "</"))


def test_page_carries_the_whole_graph_and_its_strings():
    graph = sources.build(samples.facts())
    page = render.render(graph)
    data = _embedded(page)
    assert [n["id"] for n in data["nodes"]] == [n["id"] for n in graph["nodes"]] and data["edges"] == graph["edges"]
    assert set(data["strings"]) == set(render.PAGE_KEYS) | {"state", "edge_state"}
    assert "2026-01-02 03:04:05" in data["meta"]["summary"] and "6.5" in data["meta"]["summary"]
    assert '<html lang="zh-CN">' in page and not re.search(r"__[A-Z]+__", page)
    assert "http://" not in page and "https://" not in page.replace("https://api.acme.example", "").replace("https://github.com/", "")


def test_snapshot_is_self_contained():
    """离线快照不向任何地方要东西：样式和脚本都内联，没有 src / href 指向别处。"""
    page = render.render(sources.build(samples.facts()))
    assert render.STYLE_LINK not in page and render.SCRIPT_TAGS not in page
    assert not re.search(r'<(script|link|img)[^>]*\s(src|href)=', page)
    assert "function start(G)" in page and "PANORAMA_DATA" in page


def test_a_script_end_tag_inside_the_data_cannot_cut_the_page_short():
    graph = sources.build(samples.facts())
    graph["nodes"][0]["title"] = "</script><script>alert(1)</script>"
    page = render.render(graph)
    assert page.count("</script>") == 1                                        # 只有页面自己那一个
    assert _embedded(page)["nodes"][0]["title"] == "</script><script>alert(1)</script>"


def test_summary_says_when_the_wsl_half_is_not_in_yet():
    facts = samples.facts(wsl="pending")
    del facts["timing"]["wsl_s"]
    data = _embedded(render.render(sources.build(facts)))
    assert data["meta"]["pending"] is True and "WSL" not in data["meta"]["summary"]


def test_english_page_has_no_chinese_left_in_its_own_text():
    i18n.set_language("en")
    page = render.render(sources.build(samples.facts()))
    data = _embedded(page)
    assert '<html lang="en">' in page
    leftovers = [text for text in _strings(data) if CJK.search(text)]
    assert leftovers == ["连接成功"]                                            # 体检器给的结论原样转述，不归这张字表管
    shell_text = re.sub(r"<[^>]+>", "", render.shell())
    assert not CJK.search(shell_text)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def test_write_replaces_the_file_in_one_step(tmp_path):
    graph = sources.build(samples.facts())
    target = render.write(graph, tmp_path / "out")
    assert target == tmp_path / "out" / render.PAGE_NAME and _embedded(target.read_text(encoding="utf-8"))["nodes"]
    again = render.write(sources.build(samples.facts(wsl="absent")), tmp_path / "out")
    assert again == target and not list((tmp_path / "out").glob("*.tmp"))
    assert not any(n["region"] == "wsl" for n in _embedded(target.read_text(encoding="utf-8"))["nodes"])


# ---------------------------------------------------------------- 本机服务用的那几块

def test_shell_and_static_files_hold_no_user_data():
    """外壳和静态文件不要令牌就能拿到，所以里面不能有任何采到的东西。"""
    graph = sources.build(samples.facts())
    served = render.shell() + "".join(render.asset(name).decode("utf-8") for name in render.ASSETS)
    for node in graph["nodes"]:
        for fact in node.get("facts") or []:
            value = str(fact[1])
            if len(value) >= 12:                                               # 短的值（"on"、数字）会和代码撞字
                assert value not in served, value
    assert render.DATA_NAME + " =" not in served
    assert render.STYLE_LINK in render.shell() and render.SCRIPT_TAGS in render.shell()
    assert "配置全景" in render.shell() and "连接断了" in render.shell()        # 标题和「连接断了」那句是界面文字，不是数据


def test_shell_has_no_inline_script_or_style():
    """页面带「只许同源脚本」的内容策略：外壳里出现内联脚本就是一张空白页。"""
    shell = render.shell()
    assert re.findall(r"<script[^>]*>", shell) == ['<script type="module" src="/boot.js">']      # 只引用入口模块
    assert "<style" not in shell and not re.search(r"\son[a-z]+=", shell)
    for name in render.MODULES:
        text = render.asset(name).decode("utf-8")
        assert "</script" not in text and not re.search(r"\bon(click|load|error|input)=", text), name


def test_payload_is_the_page_data_with_a_revision_and_page_info():
    graph = sources.build(samples.facts())
    data = json.loads(render.payload(graph, revision=7))
    assert data["revision"] == 7 and data["page"] == {"lang": "zh-CN", "title": "配置全景 · 大肥鱼"}
    assert data["nodes"] == json.loads(json.dumps(graph["nodes"])) and data["strings"]["lost"]
    assert data["meta"]["summary"] == render.summary(graph)


def test_token_stylesheet_is_served_before_the_page_stylesheet_and_inlined_into_the_snapshot():
    from pet import theme_tokens

    shell = render.shell()
    assert shell.index('href="/tokens.css"') < shell.index('href="/app.css"')            # 令牌在前，页面样式才引用得到
    assert render.asset("tokens.css").decode("utf-8") == theme_tokens.tokens_css()
    page = render.render(sources.build(samples.facts()))
    assert theme_tokens.tokens_css() in page and page.index("--m-accent:") < page.index("header input{")


def test_only_registered_static_files_can_be_read():
    assert render.asset("app.js").startswith(b"/*")
    for name in ("shell.html", "../render.py", "nope.js", ""):
        with pytest.raises(KeyError):
            render.asset(name)
