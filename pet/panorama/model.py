# -*- coding: utf-8 -*-
"""配置全景的图模型：页面只认这里的结构，对具体功能一无所知。

版面是「账号带 × 层」的格子：每个分区（region）落在一格里，分区里是若干列，节点在列里从上往下排。
位置和走线都由页面按这些声明算出来——这里没有坐标。加一台机器或一个账号 = 多一条带；加一项功能 =
多几个节点和几条线（见 ``pet.panorama.sources``）。

节点状态：``live`` 正在起作用（这次亲自探到）· ``ok`` 已连通 · ``warn`` 要处理 · ``bad`` 断开 / 出错 ·
``unknown`` 探测不到 · ``off`` 未启用。
连线状态：``live`` / ``ok`` 流动 · ``warn`` 待处理 · ``broken`` 断开 · ``unknown`` 探测不到 · ``off`` 未启用。
"""
from __future__ import annotations

from dataclasses import dataclass, field

NODE_STATES = ("live", "ok", "warn", "bad", "unknown", "off")
EDGE_STATES = ("live", "ok", "warn", "broken", "unknown", "off")
QUEST_LEVELS = ("bad", "warn", "unknown", "info")
SIZES = ("bar", "row", "std", "tall", "big")

#: 强调色是 Windows Phone 那一套，页面按 ``memory_distill_ui.tile_fill`` 同一条规则柔化（饱和度 ×0.6、明度 ×0.8）。
ZONES = (("personal", "#60a917"), ("work", "#0050ef"))
TIERS = ("cloud", "local")
KINDS = {
    "entry": ("#0050ef", "terminal"), "app": ("#647687", "fish"), "feature_personal": ("#00aba9", "chat"),
    "feature_work": ("#6a00ff", "news"), "link": ("#76608a", "link"), "provider": ("#fa6800", "chip"),
    "account": ("#aa00ff", "key"), "connector": ("#d80073", "plug"), "memory": ("#1ba1e2", "book"),
    "config": ("#647687", "gear"), "plugin": ("#87794e", "puzzle"), "repo": ("#6d8764", "repo"),
    "tools": ("#825a2c", "wrench"), "store": ("#f0a30a", "disk"),
    "workspace": ("#a4c400", "folder"),
}
LINES = {
    "personal": "#3fc9bb", "work": "#a78bfa", "memory": "#56b8e6", "account": "#c98bf5",
    "connector": "#ee7fb6", "config": "#cdb67c", "github": "#a9c78c", "storage": "#f2a86a",
}


@dataclass
class Graph:
    """来源往里加东西，``to_dict`` 交给页面。"""
    regions: list = field(default_factory=list)
    groups: list = field(default_factory=list)
    columns: list = field(default_factory=list)
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    quests: list = field(default_factory=list)

    def region(self, region_id: str, zone: str, tier: str, title: str, sub: str = "", pattern: str = "dots") -> None:
        self.regions.append({"id": region_id, "zone": zone, "tier": tier, "title": title, "sub": sub, "pattern": pattern})

    def group(self, group_id: str, title: str) -> None:
        """一圈外框：成员是 ``group`` 等于它的节点；``head`` 节点被点中时连同全组一起追踪。"""
        self.groups.append({"id": group_id, "title": title})

    def column(self, region: str, col: int, **options) -> None:
        """列选项：``caption`` 列头小字；``spine`` 同列连线走哪一侧（``left`` / ``right``）。"""
        self.columns.append({"region": region, "col": col, **options})

    def node(self, node_id: str, region: str, col: int, kind: str, title: str, sub: str = "", state: str = "ok",
             size: str = "std", **extra) -> str:
        """``extra``：icon lines badge facts items source page settings group head anchor gap view memory（空值不写进去）。

        ``page`` 是「去设置窗口哪一页改」的一句话；``settings`` 是已经搬到页面上的那一组设置的 id（页面出「设置」按钮）。"""
        if state not in NODE_STATES or size not in SIZES or kind not in KINDS:
            raise ValueError(f"bad node {node_id}: state={state} size={size} kind={kind}")
        if self.has(node_id):
            raise ValueError(f"duplicate node {node_id}")
        self.nodes.append({"id": node_id, "region": region, "col": col, "kind": kind, "title": title, "sub": sub,
                           "state": state, "size": size, **{k: v for k, v in extra.items() if v not in (None, "", [], ())}})
        return node_id

    def edge(self, source: str, target: str, line: str, state: str = "ok", label: str = "") -> None:
        if state not in EDGE_STATES or line not in LINES:
            raise ValueError(f"bad edge {source}->{target}: state={state} line={line}")
        self.edges.append({"from": source, "to": target, "line": line, "state": state, "label": label})

    def quest(self, level: str, text: str, node: str, action: dict | None = None) -> None:
        """``action``：页面上能点的动作 ``{"name", "agent", "side"}``（见 ``actions.py``）；没有就只是一条说明。"""
        if level not in QUEST_LEVELS:
            raise ValueError(f"bad quest level {level}")
        self.quests.append({"sev": level, "text": text, "node": node, **({"action": action} if action else {})})

    def add_fact(self, node_id: str, label: str, value: str) -> None:
        """给别的来源建的磁贴补一行事实；那块磁贴这次没出现就算了。"""
        for node in self.nodes:
            if node["id"] == node_id and value:
                node.setdefault("facts", []).append([label, value])

    def mark(self, node_id: str, **extra) -> None:
        """给别的来源建的磁贴补几个属性（如 ``view``）；那块磁贴这次没出现就算了。"""
        for node in self.nodes:
            if node["id"] == node_id:
                node.update({key: value for key, value in extra.items() if value not in (None, "", [], ())})

    def has(self, node_id: str) -> bool:
        return any(n["id"] == node_id for n in self.nodes)

    def state_of(self, node_id: str) -> str:
        return next((n["state"] for n in self.nodes if n["id"] == node_id), "unknown")

    def to_dict(self) -> dict:
        """丢掉指向不存在节点的连线和待处理（某个来源整块缺席时，别的来源声明的线不该让页面出错）。"""
        ids = {n["id"] for n in self.nodes}
        order = {level: i for i, level in enumerate(QUEST_LEVELS)}
        return {
            "regions": self.regions, "groups": self.groups, "columns": self.columns, "nodes": self.nodes,
            "edges": [e for e in self.edges if e["from"] in ids and e["to"] in ids],
            "quests": sorted((q for q in self.quests if q["node"] in ids), key=lambda q: order[q["sev"]]),
        }
