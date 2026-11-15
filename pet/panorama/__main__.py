# -*- coding: utf-8 -*-
"""``python -m pet.panorama``：采一次本机配置，写出配置全景页面并用默认浏览器打开。

不需要肥鱼在跑：直接读配置文件和钥匙串。所以这里没有「模型服务体检」的结论（那是运行中的肥鱼才有的），
使用中的服务会显示成「探测不到」。
"""
from __future__ import annotations

import argparse
import sys
import webbrowser

from ..chat.models import SecretStore
from ..config import Config
from . import probes, render, sources

OUT_SUBDIR = "panorama"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pet.panorama")
    parser.add_argument("--no-wsl", action="store_true", help="skip the WSL side")
    parser.add_argument("--no-mcp", action="store_true", help="skip `claude mcp list` inside WSL (the slow part)")
    parser.add_argument("--no-open", action="store_true", help="write the page but do not open the browser")
    args = parser.parse_args(argv)
    config = Config()
    secrets = SecretStore()
    common = {"cfg_path": config.path, "secret_get": secrets.get}
    if args.no_wsl:
        facts = probes.windows_side(config.data, **common)
        facts["wsl"] = {"absent": True}
    else:
        facts = probes.gather(config.data, with_mcp=not args.no_mcp, **common)
    graph = sources.build(facts)
    page = render.write(graph, config.dir / OUT_SUBDIR)
    print(f"{page}  ({len(graph['nodes'])} nodes, {len(graph['edges'])} edges, {len(graph['quests'])} quests, timing {facts['timing']})")
    if not args.no_open:
        webbrowser.open(page.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
