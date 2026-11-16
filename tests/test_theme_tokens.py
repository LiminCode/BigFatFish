# -*- coding: utf-8 -*-
"""颜色令牌只有一张表：Qt 的样式表和配置全景的网页都从它来。"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

from pet import theme_tokens
from pet.panorama import render


def test_qt_side_reads_the_very_same_table():
    from pet import settings_theme_qss

    assert settings_theme_qss.METRO_TOKENS is theme_tokens.METRO_TOKENS
    assert theme_tokens.METRO_TOKENS["dark"]["accent"] in settings_theme_qss.metro_stylesheet(True)


def test_both_themes_carry_the_same_token_names():
    assert set(theme_tokens.METRO_TOKENS) == {"light", "dark"}
    assert set(theme_tokens.METRO_TOKENS["light"]) == set(theme_tokens.METRO_TOKENS["dark"])


def test_css_variables_are_generated_from_the_table_for_both_themes():
    css = theme_tokens.tokens_css()
    dark, light = css.strip().split("\n")
    assert dark.startswith(":root{") and light.startswith(theme_tokens.LIGHT_SELECTOR + "{")
    for block, theme in ((dark, "dark"), (light, "light")):
        declared = dict(part.split(":", 1) for part in block[block.index("{") + 1:-1].split(";"))
        assert declared == {"--m-" + key.replace("_", "-"): value for key, value in theme_tokens.METRO_TOKENS[theme].items()}
    assert "--m-tile-hover:#33333a" in dark and "--m-field-border:#b9b9b9" in light


def test_page_stylesheet_only_uses_token_variables_that_exist():
    """网页样式里写了 var(--m-xxx) 而表里没有这个名字，浏览器不会报错，只是那条样式悄悄失效。"""
    known = set(theme_tokens.css_variables("dark"))
    used = set(re.findall(r"var\((--m-[a-z-]+)\)", render.asset("app.css").decode("utf-8")))
    assert used and used <= known, sorted(used - known)


def test_page_controls_take_their_colours_from_the_tokens_not_from_literals():
    css = render.asset("app.css").decode("utf-8")
    for selector in ("header input", ".btn", ".nb button"):
        rule = re.search(re.escape(selector) + r"\{([^}]*)\}", css).group(1)
        assert "var(--m-" in rule and not re.search(r"#[0-9a-fA-F]{3,8}\b", rule), f"{selector}: {rule}"


def test_token_module_does_not_import_qt():
    tree = ast.parse(Path(theme_tokens.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "令牌模块不依赖包里别的模块"
            imported.add((node.module or "").split(".")[0])
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}, sorted(imported)
