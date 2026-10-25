# -*- coding: utf-8 -*-
"""用真实配置跑一次个人简报（个人 API key、本地 AI-Base 克隆），只打印元信息，不打印正文。

用法：``python scripts/personal_briefing_once.py [--no-record] [--no-pull]``。默认把结果写进状态文件，
肥鱼的「个人助理」窗口打开就能看到这一份。是一次真实的模型调用，按你的 key 计费。
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pet import personal_briefing as pb, personal_vault as pv  # noqa: E402
from pet.config import Config  # noqa: E402
from pet.personal_service import resolve_chat_provider  # noqa: E402


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # 文件名里有中文；Windows 控制台默认 cp1252
    except (AttributeError, ValueError):
        pass
    config = Config()
    settings = pv.normalize(config.get(pv.CONFIG_KEY))
    provider = resolve_chat_provider(config)
    now = dt.datetime.now()
    model = settings["model"] or provider.model
    effort = settings["effort"] or provider.effort
    print(f"repo: {settings['repo_dir']} (ready={pv.repo_ready(settings['repo_dir'])})")
    print(f"provider: {provider.name} {provider.base_url} · model {model} · effort {effort}")
    pull_note = ""
    if "--no-pull" not in argv and pv.repo_ready(settings["repo_dir"]):
        ok, out = pv.pull(settings["repo_dir"], token=pv.github_token())
        print(f"git pull: {'ok' if ok else 'FAILED ' + out[-200:]}")
        pull_note = "" if ok else out
    briefing = pb.generate(now, settings, provider, pull_note=pull_note)
    print(f"ok={briefing.ok} model={briefing.model} effort={briefing.effort} seconds={briefing.seconds} "
          f"tokens_in={briefing.tokens_in} tokens_out={briefing.tokens_out} rounds={briefing.turns}")
    print(f"files read ({len(briefing.files_read)}): " + " · ".join(briefing.files_read))
    print(f"summary chars={len(briefing.summary)} markdown chars={len(briefing.markdown)} "
          f"sections={[line for line in briefing.markdown.splitlines() if line.startswith('## ')]}")
    if not briefing.ok:
        print("error:", briefing.error)
    if "--no-record" not in argv:
        pb.record(config.dir, briefing, now)
        print("recorded to", Path(config.dir) / pb.STATE_FILE)
    return 0 if briefing.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
