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

from .. import data_stores as ds
from .. import settings_table
from ..i18n import t
from . import activity, features, files, memory_scope, places
from .model import KINDS, LINES, TIERS, ZONES, Graph
from .probes import MIRROR_HOOKS

FISH_NODE = "pet"
WSL_ENTRY = "cc_wsl"
#: 一个克隆和远端核对过之后，「领先 / 落后几个提交」还能信多久。现在没有定时同步，只有手点的「现在核对」和各功能顺带的
#: pull / push 会碰远端，所以给一天；定时同步上线后改成它周期的两倍。
REMOTE_CHECK_STALE_S = 24 * 3600
#: 磁贴上的「时间轴」：三个克隆的提交都在时间轴上，所以三块克隆磁贴正面都有它，详情里也有。``show: panel`` = 页面在右栏里
#: 显示那份报告（``timeline.js``），面板头上的「在新页面打开」才真的发这个动作、另开浏览器页
TIMELINE_ACTION = {"name": "open_report", "words": "activity", "ask": False, "body": {"report": "activity"}, "show": "panel"}


def page_action(report: str) -> dict:
    """功能磁贴正面的「查看」：在浏览器里开那项功能自己的页（工作简报、个人简报、工作笔记、Slack 关注）。
    时间轴例外，在右栏里看（``TIMELINE_ACTION``）。"""
    if report == "activity":
        return TIMELINE_ACTION
    return {"name": "open_report", "words": "open_page", "ask": False, "body": {"report": report}, "icon": "eye"}
#: 镜像磁贴的状态 → 喂它的那条线的状态
_MIRROR_LINE = {"ok": "ok", "warn": "warn", "bad": "broken", "unknown": "unknown"}
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

def _src(path: str, key: str = "", env: str = "win", distro: str = "", *, folder: bool = False) -> dict | None:
    """磁贴指向磁盘上的哪里。``folder`` = 这是个目录：页面给 WSL 里的路径拼「在 VS Code 打开」的链接时要知道
    （VS Code 对远程路径分不出文件和目录，得由链接说清楚）。"""
    if not path:
        return None
    return {"path": path, "key": key, "env": env, "distro": distro, **({"dir": True} if folder else {})}


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


def _last_sync_words(last: dict | None) -> str:
    """一个克隆上一次同步怎么样了，一句话；没同步过是空串（那一行事实就不出现）。"""
    if not last:
        return ""
    result = last.get("result")
    if result == "ok":
        how = L("sync_last.ok", pulled=last.get("pulled", 0), pushed=last.get("pushed", 0))
    elif result == "noop":
        how = L("sync_last.noop")
    elif last.get("conflicts"):
        how = L("sync_last.conflicts")
    elif last.get("blocked"):
        how = L("sync_last.blocked")
    elif last.get("review"):
        how = L("sync_last.review")
    else:
        how = L("sync_last.failed")
    return f"{str(last.get('at') or '')[:16]} · {how}"


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


def _pairs(*rows) -> list:
    """清单里一行下面的说明：值是空的那几对不要。"""
    return [[label, value] for label, value in rows if value]


def _mcp_rows(servers: list[dict]) -> list[dict]:
    """登记在 ``~/.claude.json`` 里的 MCP 服务器，一条一行：是远程服务还是本地命令、连到哪、用了哪些环境变量。"""
    rows = []
    for server in servers or []:
        target, kind = str(server.get("target") or ""), str(server.get("kind") or "")
        label = L("conn.kind_remote") if re.match(r"^https?://", target) or kind in ("http", "sse") else L("conn.kind_local")
        rows.append({"name": server.get("name", ""), "state": "ok", "detail": label,
                     "more": _pairs([L("conn.kind"), L("conn.kind_detail", kind=label, type=kind) if kind else label],
                                    [L("conn.target"), target], [L("conn.env"), _join(server.get("env") or [])],
                                    [L("conn.project_only"), server.get("project", "")])})
    return rows


def _workspace_tile(g: Graph, node_id: str, region: str, owner_node: str, zone: str, spaces: dict | None, folder: str,
                    src: dict | None, probed: str) -> None:
    """一个 Claude Code 干过活的项目：一条一个，最近用过的在前；目录已经删掉的变淡，认不出路径的照实说不知道。"""
    if not spaces:
        return
    rows = []
    for project in spaces.get("projects") or []:
        exists, last = project.get("exists"), project.get("last_session") or {}
        rows.append({
            "name": memory_scope.project_label(project.get("name", "")),
            "state": "ok" if exists else "off" if exists is False else "unknown",
            "detail": L("ws.item", n=project["sessions"], when=project.get("last", "")) if project.get("sessions") else L("ws.item_memory_only"),
            "more": _pairs(
                [L("ws.path"), project.get("path") or L("ws.path_unknown")],
                [L("ws.state"), L("ws.gone") if exists is False else ""],
                [L("ws.sessions"), L("ws.sessions_value", n=project["sessions"], size=_size(project.get("bytes", 0))) if project.get("sessions") else ""],
                [L("ws.memory"), L("store.entries", n=project["memory"]) if project.get("memory") else ""],
                [L("ws.last_session"), L("ws.last_session_value", minutes=last.get("minutes", 0), cost=f"{last.get('cost', 0):.2f}",
                                         added=last.get("added", 0), removed=last.get("removed", 0)) if last else ""])})
    listed, missing, empty = spaces.get("total", 0) - spaces.get("empty", 0), spaces.get("missing", 0), spaces.get("empty", 0)
    g.node(node_id, region, 0, "workspace", L("node.workspaces"),
           L("ws.sub_missing", n=listed, missing=missing) if missing else L("ws.sub", n=listed), "ok", items=rows,
           facts=_pairs([L("fact.location"), folder],
                        [L("ws.sessions_total"), L("ws.sessions_value", n=spaces.get("sessions", 0), size=_size(spaces.get("bytes", 0)))],
                        [L("ws.empty"), L("count", n=empty) if empty else ""], [L("conn.probed"), probed],
                        [L("fact.note"), L("ws.truncated", n=len(rows)) if spaces.get("truncated") else ""]),
           source=src)
    g.edge(owner_node, node_id, "config")
    if missing:
        g.quest("info", L("quest.ws_missing", side=L(f"zone.{zone}"), n=missing), node_id)
    if empty >= WORKSPACE_EMPTY_NOTE:
        g.quest("info", L("quest.ws_empty", side=L(f"zone.{zone}"), n=empty), node_id)


def _connector_tiles(g: Graph, prefix: str, region: str, col: int, items: list[dict], owner: str, how: str,
                     probed: str = "") -> list[str]:
    """一组 connector 拆成最多两块：通的一块、其余一块——这样连线才能一条流动、一条断开 / 待处理。"""
    good = [i for i in items if i["state"] == "ok"]
    rest = [i for i in items if i["state"] != "ok"]
    known = [[L("fact.how_known"), how], *_pairs([L("conn.probed"), probed])]
    made = []
    if good or not items:
        made.append(g.node(f"{prefix}_ok", region, col, "connector", L("conn.ok_title", owner=owner),
                           L("count", n=len(good)) if items else L("conn.none"), "live" if good else "unknown", "tall",
                           items=good, facts=known))
    if rest:
        counts = [(sum(i["state"] == state for i in rest), state) for state in ("bad", "auth", "unknown")]
        state = "bad" if counts[0][0] else "warn" if counts[1][0] else "unknown"
        title = L("conn.unknown_title", owner=owner) if state == "unknown" else L("conn.rest_title", owner=owner)
        made.append(g.node(f"{prefix}_rest", region, col, "connector", title,
                           " · ".join(L(f"conn.count_{name}", n=n) for n, name in counts if n), state, "tall",
                           icon="plugoff", items=rest, facts=known))
    return made


WORKSPACE_EMPTY_NOTE = 20       # 空的项目目录多到这个数才单独提一句：零星几个不值得说
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
                  [L("fact.local_mcp"), _join(c["mcp_servers"]) or L("none")], [L("fact.other_tools"), _join(c["tools"])],
                  [L("conn.probed"), c.get("probed_at", "")]],
           source=_src(c["settings_path"]))
    if c.get("mcp_detail"):            # 这台机器上登记了 MCP 服务器才多这一块（和 WSL 一侧那块对应）
        g.node("mcp_win", "win", 0, "connector", L("node.local_mcp"), _join(s["name"] for s in c["mcp_detail"]), "ok",
               items=_mcp_rows(c["mcp_detail"]), facts=_pairs([L("fact.source"), "~/.claude.json → mcpServers"],
                                                              [L("conn.probed"), c.get("probed_at", "")]),
               source=_src(c.get("state_path", ""), "mcpServers"))
        g.edge("cc_win", "mcp_win", "connector")
    g.node("set_win", "win", 0, "config", "settings.json", L("hooks.sub", n=len(hooks)), "live" if hooks else "bad" if link_on else "off",
           facts=[[L("fact.hooks_fish"), _join(hooks) or L("none")], [L("fact.hooks_all"), _join(c["hooks"])],
                  [L("fact.modified"), c["settings_mtime"]]], source=_src(c["settings_path"], "hooks"))
    _claude_md_node(g, "md_win", "win", c["claude_md"], L("writer.personal"), _src(c["claude_md"].get("path", "")))
    g.node("mem_win", "win", 0, "memory", L("node.project_memory"), L("memory.sub", n=c["memory_count"], total=c["projects"]), "ok",
           icon="stack", items=[{"name": re.sub(r"^[A-Za-z]--Users-[^-]+-", "", m["name"]), "state": "ok",
                                 "detail": L("memory.item", n=m["files"], when=m["mtime"])} for m in c["memory_projects"]],
           facts=[[L("fact.location"), "~/.claude/projects/<project>/memory/"]],
           source=_src(c["memory_projects"][0]["path"] if c["memory_projects"] else ""))
    home_win = c.get("home", "")
    win_projects = home_win + ("\\" if "\\" in home_win else "/") + ".claude" + ("\\" if "\\" in home_win else "/") + "projects" if home_win else ""
    _workspace_tile(g, "ws_win", "win", "cc_win", "personal", c.get("workspaces"), win_projects, _src(win_projects, folder=True),
                    c.get("probed_at", ""))
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
    if link_on and not hooks:        # 页面上能直接「修复」：动作走 POST /api/actions/repair_hooks，先问一次同意（ADR 0006）
        g.quest("bad", L("quest.link_no_hooks", side=L("side.win")), "set_win",
                action={"name": "repair_hooks", "agent": "claude", "side": "win"})
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
        view = {"face": page_action(feature.report), "actions": [page_action(feature.report)]} if feature.report else {}
        g.node(node_id, "win", column, kind, L(f"feature.{feature.id}"), sub, "ok" if s["enabled"] else "off", "row",
               icon=feature.icon, group=FISH_NODE, facts=facts, source=_src(f["cfg_path"], feature.config_key),
               page=L(f"page.{feature.page}") if feature.page else "",
               settings=feature.settings_group or settings_table.group_for_config_key(feature.config_key), **view)
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
    src = lambda path, key="", folder=False: _src(path, key, "wsl", distro, folder=folder)  # noqa: E731
    g.node("acct_work", "cloud_work", 1, "account", L("node.acct_work"), account["email"] or L("unknown_account"),
           "ok" if w["credentials_file"] else "bad", "big", lines=[account["organization"], L("acct.used_by_wsl")],
           facts=[[L("fact.account"), account["email"]], [L("fact.organization"), account["organization"]],
                  [L("fact.credentials"), L("fact.credentials_oauth")]], source=src(w["credentials_path"]))
    detail = {"ok": L("conn.connected"), "auth": L("conn.needs_auth")}
    checked = w.get("mcp_probed_at", "")
    items = [{"name": row["name"].replace("claude.ai ", ""), "state": row["state"], "detail": detail.get(row["state"], row["detail"]),
              **({"more": more} if (more := _pairs(
                  [L("conn.target"), row.get("target", "")],
                  [L("conn.kind"), L(f"conn.kind_{row['kind']}") if row.get("kind") in ("remote", "local") else ""],
                  [L("conn.probed"), checked if row.get("target") else ""])) else {})}
             for row in w.get("connectors") or []]
    looked = w.get("probed_at", "")
    if looked and f.get("refreshing"):                     # 图上垫着上一轮的结果，新的一轮还在路上
        looked = L("probe.refreshing", when=looked)
    how = L("conn.how_work", seconds=w.get("mcp_probe_seconds")) if w.get("connectors") is not None else L("conn.how_skipped")
    tiles = _connector_tiles(g, "conn_w", "cloud_work", 2, items, L("zone.work"), how, checked)
    hooks = _hook_events(w["hooks"])
    link_on = f["features"]["link_wsl"]["enabled"]
    g.node(WSL_ENTRY, "wsl", 0, "entry", L("node.claude_cli"), _model_line(w["model"], w["effort"]), "ok",
           facts=[[L("fact.model"), w["model"]], [L("fact.effort"), w["effort"]], [L("fact.allow_rules"), L("count", n=w["allow_rules"])],
                  [L("fact.distro"), distro], [L("fact.how_called"), L("wsl.how_called")], [L("conn.probed"), looked]],
           source=src(w["settings_path"]))
    g.node("set_wsl", "wsl", 0, "config", "settings.json", L("hooks.sub", n=len(hooks)), "live" if hooks else "bad" if link_on else "off",
           facts=[[L("fact.hooks_fish"), _join(hooks) or L("none")], [L("fact.hooks_all"), _join(w["hooks"])],
                  [L("fact.modified"), w["settings_mtime"]]], source=src(w["settings_path"], "hooks"))
    _claude_md_node(g, "md_wsl", "wsl", w["claude_md"], L("writer.work"), src(w["claude_md"].get("path", "")))
    g.node("mem_wsl", "wsl", 0, "memory", L("node.project_memory"), L("memory.sub", n=w["memory_count"], total=w["projects"]), "ok",
           icon="stack", facts=[[L("fact.location"), "~/.claude/projects/<project>/memory/"], [L("fact.distilled"), L("count", n=w["distilled_files"])]],
           source=src(home + "/.claude/projects", folder=True))
    _workspace_tile(g, "ws_wsl", "wsl", WSL_ENTRY, "work", w.get("workspaces"), home + "/.claude/projects",
                    src(home + "/.claude/projects", folder=True), w.get("probed_at", ""))
    g.node("mcp_wsl", "wsl", 1, "connector", L("node.local_mcp"), _join(w["mcp_servers"]) or L("none"), "ok", gap=74,
           items=_mcp_rows(w.get("mcp_detail")),
           facts=_pairs([L("fact.source"), "~/.claude.json → mcpServers"], [L("conn.probed"), w.get("probed_at", "")]),
           source=src(w["state_path"], "mcpServers"))
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
        g.quest("bad", L("quest.link_no_hooks", side=L("side.wsl")), "set_wsl",
                action={"name": "repair_hooks", "agent": "claude_wsl", "side": "wsl"})


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

    def vault(node_id: str, column_: int, title: str, info: dict, push: str, check: dict | None = None,
              sync: dict | None = None, last: dict | None = None, more: list | None = None, region: str = "win",
              src: dict | None = None, extra: list | None = None) -> str:
        """一个克隆的磁贴；返回它到 GitHub 那条线该是什么状态（``""`` = 没有特别要说的，按调用方的默认）。

        领先 / 落后是按上一次碰到远端时的样子算的，所以**没核对过、核对得太久、或最近一次没连上，就不许显示绿色**：
        磁贴和线都是「探测不到」，待处理里说一句。``check``（「现在核对」，只 fetch）和 ``sync``（「现在同步」，提交、拉取、推送）
        是两个动作，只有肥鱼自己的 git 够得着的克隆才给：磁贴详情里两个一直都在，待处理里各挂在最相关的那一条上。
        已经知道有差距（领先或落后）时照旧是「要处理」——知道的坏消息比不知道更该先看见。

        正面的 ``face`` 是「时间轴」：每个克隆的提交都在那一页上。``region`` / ``src``：WSL 里的克隆落在 WSL 那一格，
        指向 WSL 里的路径；``extra`` 是再补的几行事实。"""
        source_ = src or _src(info["path"])
        if not info["exists"]:
            g.node(node_id, region, column_, "repo", title, L("missing_dir"), "bad", anchor="bottom",
                   facts=[[L("fact.push_via"), push]], source=source_)
            return ""
        unpushed, behind, dirty = info.get("unpushed"), info.get("behind"), info.get("dirty")
        checked, age, failed = info.get("checked_at") or "", info.get("checked_age_s"), bool(info.get("check_failed"))
        stale = failed or age is None or age > REMOTE_CHECK_STALE_S
        gap = bool(unpushed or behind)
        count = lambda n: "" if n is None else L("count", n=n) if n else L("none")  # noqa: E731
        short = lambda n: "?" if n is None else str(n)  # noqa: E731
        g.node(node_id, region, column_, "repo", title,
               " · ".join(part for part in (L("vault.sub", ahead=short(unpushed), behind=short(behind)),
                                            L("vault.sub_dirty") if dirty else "") if part),
               "warn" if gap else "unknown" if stale else "ok", anchor="bottom",
               lines=[L("vault.check_failed") if failed else L("vault.checked", when=checked[5:]) if checked else L("vault.never_checked")],
               actions=[action for action in (check, sync, *(more or [])) if action],   # more：详情里再多放的动作（「时间轴」）
               face=TIMELINE_ACTION,
               facts=[[L("fact.remote"), info["remote"]], [L("fact.branch"), info["branch"]], [L("fact.last_commit"), info["last_commit"]],
                      [L("fact.unpushed"), count(unpushed)], [L("fact.behind"), count(behind)],
                      [L("fact.dirty"), "" if dirty is None else L("has") if dirty else L("none")],
                      [L("fact.checked"), checked or L("vault.never_checked")],
                      [L("fact.check_failed"), L("has") if failed else ""],
                      [L("fact.last_sync"), _last_sync_words(last)],
                      [L("fact.note"), L("vault.counts_note")],
                      [L("fact.push_via"), push], *(extra or [])], source=source_)
        # 待处理旁边的按钮：「太久没核对」那条给「现在核对」（先弄清真相，只读）；有东西要对齐的——落后、领先、没提交的
        # 改动——给「现在同步」，挂在其中最要紧的一条上（挂几条就是几个一样的按钮）。两个按钮在磁贴详情里一直都有。
        carrier = "behind" if behind else "unpushed" if unpushed else "dirty"
        if unpushed:
            g.quest("warn", L("quest.unpushed", name=title, n=unpushed), node_id, action=sync if carrier == "unpushed" else None)
        if behind:
            g.quest("warn", L("quest.behind", name=title, n=behind), node_id, action=sync if carrier == "behind" else None)
        if stale:
            text = L("quest.check_failed", name=title) if failed else L("quest.stale", name=title, when=checked) if checked \
                else L("quest.never_checked", name=title)
            g.quest("unknown", text, node_id, action=check)
        if last and last.get("conflicts") and unpushed and behind:
            # 上次同步撞了冲突、已经撤回：现在是两边各多几个提交。等用户自己解决并推上去（领先或落后归零）这条才消失
            g.quest("warn", L("quest.sync_conflict", name=title, n=last["conflicts"]), node_id)
        if dirty:
            changes, deletions = info.get("changes"), info.get("deletions")
            text = L("quest.dirty", name=title) if not changes else L("quest.changes_deleted", name=title, n=changes, d=deletions) \
                if deletions else L("quest.changes", name=title, n=changes)
            g.quest("info", text, node_id, action=sync if carrier == "dirty" else None)
        return "warn" if gap else "unknown" if stale else ""

    personal_line = vault("vault_personal", 1, L("node.vault", name=_folder(personal["path"])), personal, L("vault.push_windows"),
                          check={"name": "check_remote", "words": "check", "ask": False, "body": {"repo": "personal"}},
                          sync={"name": "sync_vault", "words": "sync", "body": {"repo": "personal"}},
                          more=[TIMELINE_ACTION], last=(f.get("vault_sync") or {}).get("personal"))
    clone = (f.get("wsl") or {}).get("clone") if _wsl_ready(f) else None       # 老的 WSL 探针结果没有这一项
    mirror_state = _work_mirror(g, f, clone)                                   # 紧贴在个人克隆下面：它就在那个克隆里
    work_line = vault("vault_work", 3, L("node.vault", name=_folder(work["path"])), work, L("vault.push_wsl"), more=[TIMELINE_ACTION])
    token_line = "ok" if token["present"] else "unknown"
    g.edge(FISH_NODE, "gh_personal", "github", token_line)      # 知识库同步、GitHub 连接器；配置备份那条线见 storage
    if "github" in personal["remote"]:
        g.edge("vault_personal", "gh_personal", "github", personal_line or token_line)
    if _wsl_ready(f):
        hosts = [h for h in f["wsl"]["ssh_hosts"] if "." in h and not h[0].isdigit()]
        g.node("gh_work", "cloud_work", 0, "repo", L("node.github", owner=_owner(work["remote"]) or L("zone.work")), " · ".join(hosts), "ok", "big",
               icon="github", lines=["gh · ssh"],
               facts=[[L("fact.remote"), work["remote"]], [L("fact.ssh_hosts"), _join(f["wsl"]["ssh_hosts"])],
                      [L("fact.credentials"), L("github.work_credentials")]])
        g.edge(WSL_ENTRY, "gh_work", "github", "ok", "gh / ssh")
        if "github" in work["remote"]:
            g.edge("vault_work", "gh_work", "github", work_line or "ok")
        if clone:
            # 公司侧 Claude 在 WSL 克隆里随时提交、推送；那个克隆的 git 钩子把每次提交单向镜像进个人克隆的 4-Work
            distro = f["wsl"].get("distro", "")
            clone_line = vault("vault_wsl", 1, L("node.vault", name=_folder(clone["path"])), clone, L("vault.push_self"),
                               more=[TIMELINE_ACTION], region="wsl", src=_src(clone["path"], "", "wsl", distro, folder=True),
                               extra=[[L("fact.hooks_path"), clone.get("hooks_path") or L("mirror.no_hooks")]])
            g.edge(WSL_ENTRY, "vault_wsl", "memory")
            if "github" in (clone.get("remote") or ""):
                g.edge("vault_wsl", "gh_work", "github", clone_line or "ok")
            if mirror_state:
                g.edge("vault_wsl", "mirror_work", "storage", _MIRROR_LINE[mirror_state], L("edge.mirror"))


def _work_mirror(g: Graph, f: dict, clone: dict | None) -> str:
    """个人克隆里的工作知识库镜像（``4-Work``）：一块磁贴，返回它的状态（没有镜像是 ``""``，不出磁贴）。

    镜像说明里记着源提交；和 WSL 克隆此刻的提交号一比就知道跟上没有。比不了（WSL 那一半还没到、克隆不在）就不许绿。
    钩子没装（``core.hooksPath`` 不是 ``.githooks``）或镜像日志最后一行是报错 = 断了：以后的提交都不会过来。"""
    mirror = f.get("work_mirror") or {}
    if not mirror.get("exists"):
        return ""
    commit, title = mirror.get("commit") or "", L("node.mirror", name=_folder(mirror.get("path", "")))
    present = bool(clone and clone.get("exists"))
    log = ((f.get("wsl") or {}).get("mirror_log") or {}) if present else {}
    state, quest = "unknown", None
    if present:
        head = clone.get("head") or ""
        if clone.get("hooks_path") != MIRROR_HOOKS:
            state, quest = "bad", L("quest.mirror_no_hooks", name=title)
        elif log.get("state") == "error":
            state, quest = "bad", L("quest.mirror_failed", name=title, text=log.get("text", ""))
        elif head and commit and (head.startswith(commit) or commit.startswith(head)):
            state = "ok"
        elif log.get("state") == "skip":
            state, quest = "warn", L("quest.mirror_skipped", name=title, text=log.get("text", ""))
        else:
            state, quest = "warn", L("quest.mirror_behind", name=title, source=head or "?", mirror=commit or "?")
    stamp = lambda text: (text or "")[5:16].replace("T", " ")  # noqa: E731
    run = (L("mirror.run_ok", when=stamp(log.get("at")), commit=log.get("commit", "")) if log.get("state") == "ok"
           else log.get("text", "") or L("mirror.run_none")) if present else ""
    g.node("mirror_work", "win", 1, "repo", title, L("mirror.sub", commit=commit or "?", when=stamp(mirror.get("at"))),
           state, anchor="bottom", icon="stack", lines=[L("mirror.read_only")],
           facts=[[L("fact.mirror_source"), commit], [L("fact.mirror_source_at"), mirror.get("at", "")], [L("fact.mirror_run"), run],
                  [L("fact.hooks_path"), (clone.get("hooks_path") or L("mirror.no_hooks")) if present else ""],
                  [L("fact.note"), L("mirror.note")]], source=_src(mirror.get("path", ""), folder=True))
    if quest:
        g.quest("bad" if state == "bad" else "warn", quest, "mirror_work")
    g.edge("mirror_work", "vault_personal", "storage", "ok", L("edge.mirror_inside"))
    return state


#: 一次运行的结果 → 历史条上那一格的颜色（节点状态那一套）
_RUN_STATES = {"ok": "ok", "noop": "unknown", "needs_you": "warn", "failed": "bad", "skipped": "off"}
#: 开着、却超过这么多个周期没跑过：算「迟了」（电脑一直睡着、肥鱼没开，或服务出了问题）
SCHEDULE_LATE_AFTER = 2
#: 每天一次的功能，超过这么久没跑才算迟：工作日才跑的简报，周五到周一隔三天是正常的
DAILY_LATE_S = 4 * 86400


@source
def vault_schedule(g: Graph, f: dict) -> None:
    """「知识库定时同步」那块磁贴上和时间有关的部分：节奏、上次 / 下次、最近几次的历史条。

    定时不是一种新东西，是这块功能磁贴的属性（它本身由 ``fish_features`` 按功能表建好了）；这里只往上补。
    数据来自运行记录（``probes.vault_schedule``），不是配置——配置只说「该多久跑一次」，这里说「实际跑了没有」。
    开着却超过两个周期没跑过，磁贴变琥珀、待处理里多一条「迟了」：该跑没跑要有人看得见。"""
    node, info = "f_vault_sync", f.get("vault_schedule") or {}
    settings = info.get("settings")
    if not settings or not g.has(node):
        return
    runs, age, interval = info.get("runs") or [], info.get("last_age_s"), settings["interval_minutes"]
    idle = L("schedule.idle", n=settings["idle_minutes"]) if settings["idle_minutes"] and settings["mode"] != "watch" else L("schedule.idle_off")
    mode = L(f"schedule.mode.{settings['mode']}") if settings["mode"] in ("auto", "ask", "watch") else settings["mode"]
    for label, value in ([L("fact.schedule_mode"), mode], [L("fact.schedule_every"), L("when.every", n=interval)],
                         [L("fact.schedule_idle"), idle],
                         [L("fact.schedule_last"), f"{runs[0].get('at', '')[:16]} · {activity.describe(runs[0])}" if runs else L("schedule.never")]):
        g.add_fact(node, label, value)
    late = _history(g, node, runs, age, settings["enabled"], SCHEDULE_LATE_AFTER * interval * 60)
    if settings["enabled"]:
        g.mark(node, sub=f"{L('when.every', n=interval)} · {mode}")
    if late:
        g.quest("warn", L("quest.schedule_late", when=runs[0].get("at", "")[:16], n=interval), node)


def _history(g: Graph, node: str, runs: list, age, enabled: bool, late_after_s) -> bool:
    """给一块功能磁贴补上运行历史：详情里每次一行（``items``），开着的还要磁贴上那排色块（改成 ``tall`` 才画得出）、
    「上次 HH:MM」那一行。开着、而且最近一次已经超过 ``late_after_s`` 秒（``None`` = 这项功能不判断）= 迟了：磁贴变琥珀。
    返回是不是迟了（待处理那一句由调用方说，各有各的说法）。关着的功能只留历史，不改样子。"""
    items = [{"name": str(run.get("at") or "")[5:16], "state": _RUN_STATES.get(run.get("result"), "unknown"),
              "detail": f"{activity.trigger_name(run.get('trigger'))} · {activity.describe(run)}"} for run in runs]
    if not enabled:
        g.mark(node, items=items)
        return False
    late = bool(late_after_s) and age is not None and age > late_after_s
    last = L("schedule.late") if late else L("schedule.last", when=runs[0].get("at", "")[11:16]) if runs else L("schedule.never")
    g.mark(node, items=items, size="tall", lines=[last], state="warn" if late else "ok")
    return late


@source
def schedules(g: Graph, f: dict) -> None:
    """功能表里登记了任务名的功能（工作简报、个人简报、Slack 关注……）：磁贴上补运行历史和「上次运行」，该判断的判断迟没迟。

    加一项定时功能 = 功能表那一行写上 ``jobs``（它在运行记录里的任务名）和 ``late``（怎么算迟），再让它往运行记录里写
    （``run_recording.Recorder`` 接它的信号）；这里和页面都不用动。知识库定时同步有自己的来源（上面那个）：它还要写模式。"""
    info = f.get("schedules") or {}
    for feature in features.FEATURES:
        node, entry = f"f_{feature.id}", info.get(feature.id)
        if not feature.jobs or feature.id == "vault_sync" or entry is None or not g.has(node):
            continue
        s, runs = f["features"][feature.id], entry.get("runs") or []
        g.add_fact(node, L("fact.schedule_last"), f"{runs[0].get('at', '')[:16]} · {activity.describe(runs[0])}" if runs else L("schedule.never"))
        late_after = DAILY_LATE_S if feature.late == "daily" else SCHEDULE_LATE_AFTER * s["every_minutes"] * 60 if feature.late == "interval" else None
        if _history(g, node, runs, entry.get("last_age_s"), s["enabled"], late_after):
            g.quest("warn", L("quest.job_late", name=L(f"feature.{feature.id}"), when=runs[0].get("at", "")[:16]), node)


# ───────────────────────── 存储 ─────────────────────────

_WRITER_NAMES = {"claude_code": "Claude Code"}
QUEST_NAMES = 5             # 一条待处理里最多点几个名字，其余折成「等 N 种」


def _size(n: int) -> str:
    for unit, step in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= step:
            return f"{n / step:.1f} {unit}"
    return f"{n} B"


def _parent(path: str) -> str:
    return re.split(r"[/\\][^/\\]*$", path or "")[0]


def _root_paths(f: dict) -> dict:
    """存储表的每个根在这台机器上是哪里（钥匙串、系统登记项不是路径，给一句话）。"""
    win, wsl, seen = f["win"], f.get("wsl") or {}, f.get("storage") or {}
    home = win.get("home", "")
    sep = "\\" if "\\" in home else "/"
    return {"data": (seen.get("data") or {}).get("path") or _parent(f.get("cfg_path", "")),
            "home": home, "claude_home": home + sep + ".claude" if home else "",
            "claude_home_wsl": wsl["home"] + "/.claude" if wsl.get("home") else "",
            "keyring": t("stores.root.keyring"), "os": t("stores.root.os")}


def _seen(f: dict) -> dict:
    """根 → {存储 id: 这台机器上此刻有多少}。没核对过的根不在里面（那些只按存储表列出，不说有没有）。"""
    surveyed = f.get("storage") or {}
    seen = {root: surveyed[root].get("stores") or {} for root in ("data", "claude_home", "home") if root in surveyed}
    wsl_survey = (f.get("wsl") or {}).get("storage")
    if isinstance(wsl_survey, dict) and _wsl_ready(f):         # WSL 那边的探针自己数的（老结果没有这一段）
        seen["claude_home_wsl"] = wsl_survey.get("stores") or {}
    keys = sum(bool(p["key"]["present"]) for p in f["providers"]) + bool(f["github_token"]["present"])
    seen["keyring"] = {"api_keys": {"entries": keys}} if keys else {}
    return seen


def _restore_text(store: ds.Store) -> str:
    restore = store.restore
    what = L("restore.uncovered", plan=restore.plan) if ds.standing(store) == "local" else L(f"restore.{restore.source}", via=restore.via)
    return L("restore.line", what=what, why=t(f"stores.{ds.text_key(store)}.why"))


def _store_item(store: ds.Store, counts: dict | None, where: str) -> dict:
    """分组磁贴里的一行。``counts`` 是这个根核对出来的数；``None`` = 这个根没核对过。"""
    key, count = ds.text_key(store), (counts or {}).get(store.id)
    if counts is None:
        detail = ""
    elif not count:
        detail = L("store.absent")
    elif "entries" in count:
        detail = L("store.entries", n=count["entries"])
    else:
        detail = L("store.files", n=count["files"], size=_size(count["bytes"]), when=count["mtime"])
    state = "off" if counts is not None and not count else "warn" if ds.standing(store) == "local" else "ok"
    writers = _join(L("who.user") if w == "user" else _WRITER_NAMES.get(w, w) for w in store.writers)
    return {"id": store.id, "name": t(f"stores.{key}.name"), "state": state, "detail": detail,
            **({"view": store.id} if _can_view(store, counts) else {}),
            "more": [[L("store.holds"), t(f"stores.{key}.holds")],
                     [L("store.where"), L("store.where_value", root=where, patterns=", ".join(store.patterns))],
                     [L("fact.writer"), writers], [L("store.restore"), _restore_text(store)]]}


def _can_view(store: ds.Store, counts: dict | None) -> bool:
    """这一项能不能在页面上打开看：在查看名单里，而且刚才数到这台机器上确实有它的文件。"""
    return files.viewable(store.id) and bool((counts or {}).get(store.id))


def _some(names: list[str]) -> str:
    shown = _join(names[:QUEST_NAMES])
    return shown + L("and_more", n=len(names) - QUEST_NAMES) if len(names) > QUEST_NAMES else shown


def _backup_now(f: dict) -> tuple[str, str, str, str]:
    """配置备份此刻的状态 →（磁贴状态，去 GitHub 那条线的状态，一句话，待处理的文字；没有待处理是空串）。"""
    b = (f.get("storage") or {}).get("config_backup") or {}
    if not (b.get("auto") and b.get("repo") and f["github_token"]["present"]):
        return "warn", "off", L("backup.off"), L("quest.backup_off")
    if b.get("paused"):
        return "warn", "warn", L("backup.paused"), L("quest.backup_paused")
    if b.get("error"):
        return "warn", "broken", L("backup.failed", error=b["error"]), L("quest.backup_failed", error=b["error"])
    if not b.get("backed_up_at"):
        return "unknown", "unknown", L("backup.never"), ""
    return "ok", "ok", L("backup.last", when=b["backed_up_at"]), ""


@source
def storage(g: Graph, f: dict) -> None:
    """存储表画到图上：每个地方（``places.PLACES``）按「硬盘没了会怎样」分成最多三块磁贴，点开是里面的每一项。

    设计来自存储表，此刻的实际情况来自 ``facts["storage"]``（没有这一段也画得出来，只是不说各有多少）。
    """
    paths, seen = _root_paths(f), _seen(f)
    wsl = f.get("wsl") or {}
    surveyed = {**(f.get("storage") or {}), **({"claude_home_wsl": wsl["storage"]} if "claude_home_wsl" in seen else {})}
    for place in places.PLACES:
        if not g.has(place.owner) or (place.wsl and not _wsl_ready(f)):
            continue
        owner, short = L(f"place.{place.label}"), L(f"place_tile.{place.label}")    # 待处理里说全名，磁贴上地方小，说短的
        src = _src(paths.get(place.roots[0], ""), "", "wsl" if place.wsl else "win", wsl.get("distro", "") if place.wsl else "",
                   folder=True)
        members = [s for s in ds.STORES if s.root in place.roots and s.id not in places.OWN_TILE]
        checked = any(root in seen for root in place.roots)
        for stand in ds.STANDINGS:
            stores = [s for s in members if ds.standing(s) == stand]
            if not stores:
                continue
            items = [_store_item(s, seen.get(s.root), paths.get(s.root, "")) for s in stores]
            present = [i["name"] for i in items if i["state"] != "off"]
            counts = [c for c in ((seen.get(s.root) or {}).get(s.id) for s in stores) if c and "files" in c]
            files, size = sum(c["files"] for c in counts), sum(c["bytes"] for c in counts)
            sub = L("store.sub", owner=short, n=len(present), size=_size(size)) if counts else L("store.sub_plain", owner=short, n=len(present))
            state = "warn" if stand == "local" and present else "ok"
            where = _join(dict.fromkeys(paths.get(s.root, "") for s in stores))
            facts = [[L("fact.location"), where], [L("store.total"), L("store.total_value", n=files, size=_size(size)) if counts else ""],
                     [L("fact.basis"), L("store.basis")], [L("fact.note"), "" if checked else L("store.not_surveyed")]]
            backed_up = stand == "kept" and any(s.restore.via == "config_backup" for s in stores)
            if backed_up:
                state, line_state, sentence, quest = _backup_now(f)
                sub = sentence
                facts.insert(1, [L("fact.config_backup"), sentence])
            node_id = g.node(f"st_{place.id}_{stand}", place.region, place.col, "store", L(f"store.tile.{stand}"), sub, state,
                             "row" if stand == "free" else "std", items=items, facts=facts, source=src,
                             page=L("page.config_backup") if backed_up else "")
            g.edge(place.owner, node_id, "storage")
            if backed_up:
                g.edge(node_id, "gh_personal", "github", line_state, L("edge.config_backup"))
                if quest:
                    g.quest("warn", quest, node_id)
            if stand == "local" and present:
                g.quest("warn", L("quest.local_only", owner=owner, n=len(present), names=_some(present)), node_id)
        unknown = [name for root in place.roots for name in (surveyed.get(root) or {}).get("unknown", [])]
        total = sum((surveyed.get(root) or {}).get("unknown_count", 0) for root in place.roots)
        if unknown:
            node_id = g.node(f"st_{place.id}_unknown", place.region, place.col, "store", L("store.tile.unknown"),
                             L("store.sub_unknown", owner=short, n=total), "unknown", "row",
                             items=[{"name": name, "state": "unknown", "detail": ""} for name in unknown],
                             facts=[[L("fact.location"), paths.get(place.roots[0], "")], [L("fact.note"), L("store.unknown_note")]], source=src)
            g.edge(place.owner, node_id, "storage", "unknown")
            g.quest("unknown", L("quest.unregistered", owner=owner, n=total, names=_some(unknown)), node_id)
        if any((surveyed.get(root) or {}).get("truncated") for root in place.roots):
            g.quest("info", L("quest.truncated", owner=owner), place.owner)
    for store in ds.STORES:
        tile = places.OWN_TILE.get(store.id) or places.ALSO_ON.get(store.id)
        if tile:
            g.add_fact(tile, L("store.restore"), _restore_text(store))
            if _can_view(store, seen.get(store.root)):
                g.mark(tile, view=store.id)


@source
def feature_writes(g: Graph, f: dict) -> None:
    """功能表里声明的「写到哪」。放在最后：目标节点由前面的来源建。"""
    for feature in features.FEATURES:
        s = f["features"][feature.id]
        for target, line in s["writes"]:
            if not s["enabled"]:
                state = "off"
            elif feature.route == "link" and line == "config":   # 联动写的是那边的设置文件：线通不通，看 hooks 在不在
                state = "live" if g.state_of(target) == "live" else "broken"
            elif g.state_of(f"f_{feature.id}") == "warn":        # 这项功能自己有事要说（定时同步迟了）：线跟着琥珀
                state = "warn"
            else:
                state = "ok"
            g.edge(f"f_{feature.id}", target, line, state)


# ───────────────────────── 记忆按作用域 ─────────────────────────

_MEMORY_TILES = {"win": ("mem_win", "md_win"), "wsl": ("mem_wsl", "md_wsl")}


def _memory_sides(f: dict) -> list[tuple[str, dict | None]]:
    sides = [("win", f["win"].get("memory_index"))]
    if _wsl_ready(f):
        sides.append(("wsl", f["wsl"].get("memory_index")))
    return sides


def memory_view(f: dict) -> dict:
    """页面上「记忆一览」要的那一份：``memory_scope.analyse`` 的结果配上界面文字。

    每个标记带一句话说明和「另一份在哪」；这台机器上打得开的条目带 ``view``（WSL 一侧的这一步还打不开）。
    """
    view = memory_scope.analyse(_memory_sides(f))
    titles = {"win": L("memory.side.win"), "wsl": L("memory.side.wsl", distro=(f.get("wsl") or {}).get("distro", "")).rstrip(" ·")}
    short = {"win": L("zone.personal"), "wsl": L("zone.work")}

    def dress(row: dict) -> None:
        where = _join(dict.fromkeys(L("memory.twin", side=short.get(t["side"], t["side"]), where=t["project"] or L("memory.global_short"))
                                    for t in row.pop("twins")))
        row["flags"] = [{"kind": flag, "label": L(f"memory.flag.{flag}"), "tip": L(f"memory.tip.{flag}", where=where)} for flag in row["flags"]]

    for side in view["sides"]:
        side["title"] = titles.get(side["id"], side["id"])
        # WSL 一侧的要那边数过存储才给「查看」：没数过说明是老探针的结果，那边有没有这些文件都不知道
        suffix = "" if side["id"] == "win" else "_wsl" if isinstance((f.get("wsl") or {}).get("storage"), dict) else None
        for rule in side["rules"]:
            dress(rule)
            if suffix is not None and files.viewable("claude_md" + suffix):
                rule["view"] = {"store": "claude_md" + suffix, "path": "CLAUDE.md"}
        for project in side["projects"]:
            for entry in project["entries"]:
                dress(entry)
                if suffix is not None and files.viewable("claude_memory" + suffix):
                    entry["view"] = {"store": "claude_memory" + suffix, "path": f"projects/{project['name']}/memory/{entry['file']}"}
    return view


@source
def memory_scopes(g: Graph, f: dict) -> None:
    """记忆磁贴上挂「记忆一览」的入口；哪一侧有重复的、像是放错作用域的，各留一条提示。"""
    for side in memory_scope.analyse(_memory_sides(f))["sides"]:
        memory_tile, rules_tile = _MEMORY_TILES[side["id"]]
        g.mark(memory_tile, memory=side["id"])
        g.mark(rules_tile, memory=side["id"])
        counts = side["counts"]
        if counts["dup"] or counts["misplaced"]:
            g.quest("info", L("quest.memory_flags", side=L(f"zone.{'personal' if side['id'] == 'win' else 'work'}"),
                              dup=counts["dup"], misplaced=counts["misplaced"]), memory_tile)


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
    return {**skeleton(), **graph.to_dict(), "memory": memory_view(facts),
            "meta": {"taken_at": facts.get("taken_at", ""), "timing": timing, "bridge": L("bridge"),
                     # 页面据此自己隔几秒重读：WSL 那半张还没探，或者垫着上一轮的结果、新的还在路上
                     "pending": bool(wsl.get("pending")) or not wsl or bool(facts.get("refreshing")),
                     "sources": [fn.__name__ for fn in SOURCES]}}
