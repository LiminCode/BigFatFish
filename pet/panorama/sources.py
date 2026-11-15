# -*- coding: utf-8 -*-
"""来源：把探针读到的 ``facts`` 翻译成图上的节点、连线和待处理。

每个 ``@source`` 函数管一块地方，互不知道对方；谁也不算坐标。要让图上多一样东西，就加一个来源
（大肥鱼自己的 AI 功能更简单：在 ``features.FEATURES`` 里加一行）。来源声明的连线可以指向别的来源的节点，
目标这次没出现（比如没装 WSL）时由 ``Graph.to_dict`` 丢掉，不会让页面出错。

这里是纯函数：不读盘、不起进程，测试直接喂 ``facts``。
"""
from __future__ import annotations

import re
from typing import Callable

from ..i18n import t
from . import features
from .model import KINDS, LINES, TIERS, ZONES, Graph

FISH_NODE = "pet"
WSL_ENTRY = "cc_wsl"
SOURCES: list[Callable[[Graph, dict], None]] = []


PREFIX = "panorama."


def L(key: str, **values) -> str:
    """这张图自己的文字：``L("fact.model")`` = ``t("panorama.fact.model")``。两张字表里都得有，
    ``tests/test_panorama_sources.py`` 按字面量和实际建出来的图各查一遍。"""
    return t(PREFIX + key, **values)


def source(fn):
    SOURCES.append(fn)
    return fn


# ───────────────────────── 小工具 ─────────────────────────

def _src(path: str, key: str = "", env: str = "win", distro: str = "") -> dict | None:
    return {"path": path, "key": key, "env": env, "distro": distro} if path else None


def _hook_events(hooks: dict) -> list[str]:
    return [event for event, count in (hooks or {}).items() if count.get("fish")]


def _wsl_ready(facts: dict) -> bool:
    wsl = facts.get("wsl") or {}
    return bool(wsl) and not (wsl.get("absent") or wsl.get("error") or wsl.get("pending"))


def _owner(remote: str) -> str:
    match = re.search(r"github\.com[:/]([^/]+)/", remote or "")
    return match.group(1) if match else ""


def _folder(path: str) -> str:
    """克隆目录的最后一段当磁贴名：仓库换了地方或换了名字，图上跟着变。"""
    parts = [part for part in re.split(r"[/\\]", path or "") if part]
    return parts[-1] if parts else ""


def _join(items) -> str:
    return L("list_sep").join(str(item) for item in items if item)


def _model_line(model: str, effort: str) -> str:
    return " · ".join(x for x in (model or L("default_model"), L("effort_is", effort=effort) if effort else "") if x)


def _claude_md_node(g: Graph, node_id: str, region: str, md: dict, writer: str, src: dict | None) -> None:
    if not md.get("exists"):
        g.node(node_id, region, 0, "memory", "CLAUDE.md", L("missing"), "bad", source=src)
        return
    block = L("fact.managed_block_has", n=md.get("managed_rules", 0), when=md.get("managed_updated", "")) \
        if md.get("managed_block") else L("fact.managed_block_none")
    g.node(node_id, region, 0, "memory", "CLAUDE.md", L("claude_md.sub", lines=md.get("lines", 0), rules=md.get("managed_rules", 0)),
           "ok" if md.get("managed_block") else "unknown",
           facts=[[L("fact.size"), L("fact.bytes", n=md.get("bytes", 0))], [L("fact.managed_block"), block],
                  [L("fact.modified"), md.get("mtime", "")], [L("fact.writer"), writer]], source=src)


def _connector_tiles(g: Graph, prefix: str, region: str, col: int, items: list[dict], owner: str, how: str) -> list[str]:
    """一组 connector 拆成最多两块：通的一块、其余一块——这样连线才能一条流动、一条断开 / 待处理。"""
    good = [i for i in items if i["state"] == "ok"]
    rest = [i for i in items if i["state"] != "ok"]
    made = []
    if good or not items:
        made.append(g.node(f"{prefix}_ok", region, col, "connector", L("conn.ok_title", owner=owner),
                           L("count", n=len(good)) if items else L("conn.none"), "live" if good else "unknown", "tall",
                           items=good, facts=[[L("fact.how_known"), how]]))
    if rest:
        counts = [(sum(i["state"] == state for i in rest), state) for state in ("bad", "auth", "unknown")]
        state = "bad" if counts[0][0] else "warn" if counts[1][0] else "unknown"
        title = L("conn.unknown_title", owner=owner) if state == "unknown" else L("conn.rest_title", owner=owner)
        made.append(g.node(f"{prefix}_rest", region, col, "connector", title,
                           " · ".join(L(f"conn.count_{name}", n=n) for n, name in counts if n), state, "tall",
                           icon="plugoff", items=rest, facts=[[L("fact.how_known"), how]]))
    return made


_EDGE_FOR_NODE = {"live": "live", "ok": "ok", "bad": "broken", "warn": "warn", "off": "off"}


# ───────────────────────── 来源 ─────────────────────────

@source
def regions(g: Graph, f: dict) -> None:
    win, wsl = f["win"], f.get("wsl") or {}
    g.region("cloud_personal", "personal", "cloud", L("region.cloud_personal"), win["account"]["email"], "cloud")
    g.region("win", "personal", "local", L("region.win"), f.get("computer", ""), "dots")
    if not wsl.get("absent"):
        g.region("cloud_work", "work", "cloud", L("region.cloud_work"), (wsl.get("account") or {}).get("email", ""), "cloud")
        g.region("wsl", "work", "local", L("region.wsl", distro=wsl.get("distro", "")).rstrip(" ·"), wsl.get("user", ""), "hatch")
    g.group(FISH_NODE, L("app_name"))
    g.column("win", 3, caption=L("caption.work_route"))
    g.column("wsl", 0, spine="right")


@source
def claude_code_windows(g: Graph, f: dict) -> None:
    c = f["win"]
    account = c["account"]
    g.node("acct_personal", "cloud_personal", 0, "account", L("node.acct_personal"), account["email"] or L("unknown_account"),
           "ok" if c["credentials_file"] else "bad", "big", lines=[L("acct.used_by_win")],
           facts=[[L("fact.account"), account["email"]], [L("fact.organization"), account["organization"]],
                  [L("fact.credentials"), L("fact.credentials_oauth")]], source=_src(c["credentials_path"]))
    # 个人账号的 connector 挂在 claude.ai 账号上：磁盘上只留着「连过哪些」，现状本机读不到
    items = [{"name": name.replace("claude.ai ", ""), "state": "unknown", "detail": L("conn.ever_connected")} for name in c["ever_connected"]]
    tiles = _connector_tiles(g, "conn_p", "cloud_personal", 1, items, L("zone.personal"), L("conn.how_personal")) if items else []
    hooks = _hook_events(c["hooks"])
    link_on = f["features"]["link_win"]["enabled"]
    g.node("cc_win", "win", 0, "entry", L("node.claude_cli"), _model_line(c["model"], c["effort"]), "ok",
           facts=[[L("fact.model"), c["model"]], [L("fact.effort"), c["effort"]], [L("fact.allow_rules"), L("count", n=c["allow_rules"])],
                  [L("fact.local_mcp"), _join(c["mcp_servers"]) or L("none")], [L("fact.other_tools"), _join(c["tools"])]],
           source=_src(c["settings_path"]))
    g.node("set_win", "win", 0, "config", "settings.json", L("hooks.sub", n=len(hooks)), "live" if hooks else "bad" if link_on else "off",
           facts=[[L("fact.hooks_fish"), _join(hooks) or L("none")], [L("fact.hooks_all"), _join(c["hooks"])],
                  [L("fact.modified"), c["settings_mtime"]]], source=_src(c["settings_path"], "hooks"))
    _claude_md_node(g, "md_win", "win", c["claude_md"], L("writer.personal"), _src(c["claude_md"].get("path", "")))
    g.node("mem_win", "win", 0, "memory", L("node.project_memory"), L("memory.sub", n=c["memory_count"], total=c["projects"]), "ok",
           icon="stack", items=[{"name": re.sub(r"^[A-Za-z]--Users-[^-]+-", "", m["name"]), "state": "ok",
                                 "detail": L("memory.item", n=m["files"], when=m["mtime"])} for m in c["memory_projects"]],
           facts=[[L("fact.location"), "~/.claude/projects/<project>/memory/"]],
           source=_src(c["memory_projects"][0]["path"] if c["memory_projects"] else ""))
    g.node("plug_win", "win", 0, "plugin", L("node.plugins"), _join(p.split("@")[0] for p in c["plugins"]) or L("none"), "ok",
           facts=[[L("fact.installed"), _join(c["plugins"])]])
    g.node("desktop", "win", 1, "entry", L("node.claude_desktop"), L("desktop.sub"), "ok", icon="window",
           facts=[[L("fact.note"), L("desktop.note")]])
    credentials = "ok" if c["credentials_file"] else "broken"
    g.edge("cc_win", "acct_personal", "account", credentials)
    g.edge("desktop", "acct_personal", "account", credentials)
    for tile in tiles:
        g.edge("desktop", tile, "connector", _EDGE_FOR_NODE.get(g.state_of(tile), "unknown"))
    g.edge("cc_win", "set_win", "config")
    g.edge("cc_win", "md_win", "memory")
    g.edge("cc_win", "mem_win", "memory")
    g.edge("cc_win", "plug_win", "config")
    if items:
        g.quest("unknown", L("quest.personal_connectors", n=len(items)), "conn_p_rest")
    if link_on and not hooks:
        g.quest("bad", L("quest.link_no_hooks", side=L("side.win")), "set_win")
    g.quest("info", L("quest.memory_coverage", n=c["memory_count"], total=c["projects"]), "mem_win")


@source
def model_services(g: Graph, f: dict) -> None:
    health = f["api_health"]
    for index, p in enumerate(f["providers"]):
        key = p["key"]
        if not key["present"]:
            state = "bad"
        elif p["active"]:
            state = {"ok": "live", "bad": "bad"}.get(health["state"], "unknown")
        else:
            state = "unknown"
        g.node(f"prov_{p['id']}", "cloud_personal", 2 + index, "provider", p["name"], p["model"], state, "big",
               lines=[p["host"], L("key.tail", tail=key["tail"]) if key["present"] else L("key.none")],
               badge=L("in_use") if p["active"] else "",
               facts=[[L("fact.service_id"), p["id"]], [L("fact.address"), p["base_url"]], [L("fact.model"), p["model"]],
                      [L("fact.effort"), p["effort"]], [L("fact.protocol"), p["api_format"]],
                      [L("fact.key"), L("key.where", ref=p["key_ref"], tail=key["tail"]) if key["present"] else L("key.missing")],
                      [L("fact.health"), (health["detail"] or L("health.none")) if p["active"] else L("health.only_active")]],
               source=_src(f["cfg_path"], f"chat.providers.{p['id']}"), page=L("page.ai_services"))
        if not key["present"]:
            g.quest("bad", L("quest.no_key", name=p["name"]), f"prov_{p['id']}")
        elif p["active"] and health["state"] == "bad":
            g.quest("bad", L("quest.health_bad", name=p["name"], detail=health["detail"]), f"prov_{p['id']}")
        elif not p["active"]:
            g.quest("unknown", L("quest.not_checked", name=p["name"]), f"prov_{p['id']}")


@source
def fish_features(g: Graph, f: dict) -> None:
    active = next((p for p in f["providers"] if p["active"]), None)
    health = f["api_health"]["state"]
    g.node(FISH_NODE, "win", 2, "app", L("app_name"), "", "live", "bar", group=FISH_NODE, head=True,
           facts=[[L("fact.config_file"), f["cfg_path"]], [L("fact.modified"), f["cfg_mtime"]], [L("fact.keyring"), "big-fat-fish"]],
           source=_src(f["cfg_path"]))
    off = []
    for feature in features.FEATURES:
        s = f["features"][feature.id]
        node_id = f"f_{feature.id}"
        when = s["when"] or (L("when.every", n=s["every_minutes"]) if s["every_minutes"] else "")
        if feature.route == "link":
            sub = L("link.on") if s["enabled"] else L("state.off")
        elif feature.follows_provider:
            sub = _model_line(active["model"], active["effort"]) if active else L("no_provider")
        else:
            sub = " · ".join(x for x in (s["model"] or L("follows_provider"), L("effort_is", effort=s["effort"]) if s["effort"] else "", when) if x)
        facts = [[L("fact.switch"), L("switch.on") if s["enabled"] else L("switch.off")]]
        if feature.route != "link":
            facts += [[L("fact.model"), s["model"] or L("follows_provider")], [L("fact.effort"), s["effort"] or L("follows_provider")],
                      [L("fact.when"), when],
                      [L("fact.prompt"), L("prompt.custom", n=s["prompt_chars"]) if s["prompt_chars"] else L("prompt.builtin")]]
        if feature.note:
            facts.append([L("fact.note"), L(f"note.{feature.note}")])
        kind = {"personal": "feature_personal", "work": "feature_work", "link": "link"}[feature.route]
        column = 3 if feature.route == "work" or feature.id == "link_wsl" else 2
        g.node(node_id, "win", column, kind, L(f"feature.{feature.id}"), sub, "ok" if s["enabled"] else "off", "row",
               icon=feature.icon, group=FISH_NODE, facts=facts, source=_src(f["cfg_path"], feature.config_key),
               page=L(f"page.{feature.page}") if feature.page else "")
        if not s["enabled"]:
            off.append(L(f"feature.{feature.id}"))
        if feature.route == "personal" and active:
            line_state = {"ok": "live", "bad": "broken"}.get(health, "unknown")
            g.edge(node_id, f"prov_{active['id']}", "personal", line_state if s["enabled"] else "off")
        elif feature.route == "work":
            g.edge(node_id, WSL_ENTRY, "work", ("ok" if _wsl_ready(f) else "broken" if (f.get("wsl") or {}).get("error") else "unknown")
                   if s["enabled"] else "off")
    if off:
        g.quest("info", L("quest.features_off", names=_join(off)), FISH_NODE)


@source
def claude_code_wsl(g: Graph, f: dict) -> None:
    w = f.get("wsl") or {}
    if w.get("absent"):
        return
    if not _wsl_ready(f):
        pending = bool(w.get("pending")) or not w
        g.node(WSL_ENTRY, "wsl", 0, "entry", L("node.claude_cli"), L("wsl.pending") if pending else L("wsl.failed"),
               "unknown" if pending else "bad", facts=[[L("fact.error"), w.get("error", "")]])
        if not pending:
            g.quest("bad", L("quest.wsl_failed", detail=w.get("error", "")), WSL_ENTRY)
        return
    account, home, distro = w["account"], w["home"], w.get("distro", "")
    src = lambda path, key="": _src(path, key, "wsl", distro)  # noqa: E731
    g.node("acct_work", "cloud_work", 1, "account", L("node.acct_work"), account["email"] or L("unknown_account"),
           "ok" if w["credentials_file"] else "bad", "big", lines=[account["organization"], L("acct.used_by_wsl")],
           facts=[[L("fact.account"), account["email"]], [L("fact.organization"), account["organization"]],
                  [L("fact.credentials"), L("fact.credentials_oauth")]], source=src(w["credentials_path"]))
    detail = {"ok": L("conn.connected"), "auth": L("conn.needs_auth")}
    items = [{"name": row["name"].replace("claude.ai ", ""), "state": row["state"], "detail": detail.get(row["state"], row["detail"])}
             for row in w.get("connectors") or []]
    how = L("conn.how_work", seconds=w.get("mcp_probe_seconds")) if w.get("connectors") is not None else L("conn.how_skipped")
    tiles = _connector_tiles(g, "conn_w", "cloud_work", 2, items, L("zone.work"), how)
    hooks = _hook_events(w["hooks"])
    link_on = f["features"]["link_wsl"]["enabled"]
    g.node(WSL_ENTRY, "wsl", 0, "entry", L("node.claude_cli"), _model_line(w["model"], w["effort"]), "ok",
           facts=[[L("fact.model"), w["model"]], [L("fact.effort"), w["effort"]], [L("fact.allow_rules"), L("count", n=w["allow_rules"])],
                  [L("fact.distro"), distro], [L("fact.how_called"), L("wsl.how_called")]], source=src(w["settings_path"]))
    g.node("set_wsl", "wsl", 0, "config", "settings.json", L("hooks.sub", n=len(hooks)), "live" if hooks else "bad" if link_on else "off",
           facts=[[L("fact.hooks_fish"), _join(hooks) or L("none")], [L("fact.hooks_all"), _join(w["hooks"])],
                  [L("fact.modified"), w["settings_mtime"]]], source=src(w["settings_path"], "hooks"))
    _claude_md_node(g, "md_wsl", "wsl", w["claude_md"], L("writer.work"), src(w["claude_md"].get("path", "")))
    g.node("mem_wsl", "wsl", 0, "memory", L("node.project_memory"), L("memory.sub", n=w["memory_count"], total=w["projects"]), "ok",
           icon="stack", facts=[[L("fact.location"), "~/.claude/projects/<project>/memory/"], [L("fact.distilled"), L("count", n=w["distilled_files"])]],
           source=src(home + "/.claude/projects"))
    g.node("mcp_wsl", "wsl", 1, "connector", L("node.local_mcp"), _join(w["mcp_servers"]) or L("none"), "ok", gap=74,
           facts=[[L("fact.source"), "~/.claude.json → mcpServers"]], source=src(w["state_path"], "mcpServers"))
    g.node("plug_wsl", "wsl", 1, "plugin", L("node.plugins"), L("plugins.sub", n=len(w["plugins"])), "ok",
           items=[{"name": p.split("@")[0], "state": "ok", "detail": "@" + p.split("@")[-1] if "@" in p else ""} for p in w["plugins"]],
           source=src(w["settings_path"], "enabledPlugins"))
    g.node("tools_wsl", "wsl", 1, "tools", L("node.cli_credentials"), " · ".join([t_.split("/")[-1].lstrip(".") for t_ in w["tools"]] + ["ssh"]), "ok",
           facts=[[L("fact.directories"), _join(w["tools"])], [L("fact.ssh_hosts"), _join(w["ssh_hosts"])]])
    g.edge(WSL_ENTRY, "acct_work", "account", "ok" if w["credentials_file"] else "broken")
    for tile in tiles:
        g.edge(WSL_ENTRY, tile, "connector", _EDGE_FOR_NODE.get(g.state_of(tile), "unknown"))
    for target, line in (("set_wsl", "config"), ("md_wsl", "memory"), ("mem_wsl", "memory"), ("mcp_wsl", "connector"),
                         ("plug_wsl", "config"), ("tools_wsl", "config")):
        g.edge(WSL_ENTRY, target, line)
    waiting = sum(i["state"] == "auth" for i in items)
    if waiting:
        g.quest("warn", L("quest.connectors_auth", n=waiting), "conn_w_rest")
    for i in items:
        if i["state"] == "bad":
            g.quest("bad", L("quest.connector_failed", name=i["name"], detail=i["detail"]), "conn_w_rest")
    if link_on and not hooks:
        g.quest("bad", L("quest.link_no_hooks", side=L("side.wsl")), "set_wsl")


@source
def repositories(g: Graph, f: dict) -> None:
    token, chat, backup = f["github_token"], f["chat"], f["config_backup"]
    personal, work = f["personal_vault"], f["work_vault"]
    column = 2 + len(f["providers"])
    kb = chat["knowledge_base_repo"] or (L("kb.no_repo") if chat["knowledge_base_enabled"] else L("state.off"))
    g.node("gh_personal", "cloud_personal", column, "repo", L("node.github", owner=_owner(personal["remote"]) or L("zone.personal")),
           L("key.token_tail", tail=token["tail"]) if token["present"] else L("key.no_token"), "ok" if token["present"] else "warn", "big",
           icon="github", lines=[L("github.personal_uses")],
           facts=[[L("fact.fish_token"), L("key.token_where") if token["present"] else L("none")],
                  [L("fact.github_connector"), L("switch.on") if chat["github_connector"] else L("switch.off")],
                  [L("fact.knowledge_base"), kb],
                  [L("fact.config_backup"), L("backup.value", repo=backup.get("repo") or L("backup.same_repo"), path=backup.get("path", ""),
                                               mode=L("backup.auto") if backup.get("auto") else L("backup.manual"))],
                  [L("fact.note"), L("github.no_probe")]])
    g.quest("unknown", L("quest.github_no_probe"), "gh_personal")

    def vault(node_id: str, column_: int, title: str, info: dict, push: str) -> None:
        g.node(node_id, "win", column_, "repo", title, info["last_commit"][:16] if info["exists"] else L("missing_dir"),
               "ok" if info["exists"] else "bad", anchor="bottom",
               facts=[[L("fact.remote"), info["remote"]], [L("fact.branch"), info["branch"]], [L("fact.last_commit"), info["last_commit"]],
                      [L("fact.push_via"), push]], source=_src(info["path"]))

    vault("vault_personal", 1, L("node.vault", name=_folder(personal["path"])), personal, L("vault.push_windows"))
    vault("vault_work", 3, L("node.vault", name=_folder(work["path"])), work, L("vault.push_wsl"))
    token_line = "ok" if token["present"] else "unknown"
    g.edge(FISH_NODE, "gh_personal", "github", token_line, L("edge.config_backup"))
    if "github" in personal["remote"]:
        g.edge("vault_personal", "gh_personal", "github", token_line)
    if _wsl_ready(f):
        hosts = [h for h in f["wsl"]["ssh_hosts"] if "." in h and not h[0].isdigit()]
        g.node("gh_work", "cloud_work", 0, "repo", L("node.github", owner=_owner(work["remote"]) or L("zone.work")), " · ".join(hosts), "ok", "big",
               icon="github", lines=["gh · ssh"],
               facts=[[L("fact.remote"), work["remote"]], [L("fact.ssh_hosts"), _join(f["wsl"]["ssh_hosts"])],
                      [L("fact.credentials"), L("github.work_credentials")]])
        g.edge(WSL_ENTRY, "gh_work", "github", "ok", "gh / ssh")
        if "github" in work["remote"]:
            g.edge("vault_work", "gh_work", "github")


@source
def feature_writes(g: Graph, f: dict) -> None:
    """功能表里声明的「写到哪」。放在最后：目标节点由前面的来源建。"""
    for feature in features.FEATURES:
        s = f["features"][feature.id]
        for target, line in s["writes"]:
            if not s["enabled"]:
                state = "off"
            elif feature.route == "link":   # 联动的线通不通，看那边的 hooks 在不在
                state = "live" if g.state_of(target) == "live" else "broken"
            else:
                state = "ok"
            g.edge(f"f_{feature.id}", target, line, state)


def skeleton() -> dict:
    return {
        "zones": [{"id": zone, "title": L(f"zone.{zone}"), "accent": accent} for zone, accent in ZONES],
        "tiers": [{"id": tier} for tier in TIERS],
        "kinds": {kind: {"name": L(f"kind.{kind}"), "accent": accent, "icon": icon} for kind, (accent, icon) in KINDS.items()},
        "lines": {line: {"name": L(f"line.{line}"), "tip": L(f"line_tip.{line}"), "color": color} for line, color in LINES.items()},
    }


def build(facts: dict) -> dict:
    """``facts`` → 页面要的整张图（骨架 + 分区 + 节点 + 连线 + 待处理 + meta）。"""
    graph = Graph()
    for fn in SOURCES:
        fn(graph, facts)
    timing = facts.get("timing") or {}
    wsl = facts.get("wsl") or {}
    return {**skeleton(), **graph.to_dict(),
            "meta": {"taken_at": facts.get("taken_at", ""), "timing": timing, "bridge": L("bridge"),
                     # 页面据此自己隔几秒重读：WSL 那半张还没探，或者垫着上一轮的结果、新的还在路上
                     "pending": bool(wsl.get("pending")) or not wsl or bool(facts.get("refreshing")),
                     "sources": [fn.__name__ for fn in SOURCES]}}
