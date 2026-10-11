# -*- coding: utf-8 -*-
"""洗牌式抽取：一副牌全部出过一轮才重洗（彩蛋弹窗的图、自言自语的配图与台词）。

此前这几处都是每次独立地 ``random.choice``——不记得上次出过什么。35 张图连开 8 次
就有 58% 的概率看到重复，5 句台词更是每句每次 14%。洗牌式保证：一轮之内不重复；
重洗后的第一张不等于上一轮的最后一张。

每副牌记三样东西（``STORE`` 里按牌堆的键存）：

- ``queue``：这一轮还没出的，按将要出的顺序；
- ``seen``：这一轮已经出过的；
- ``last``：最近出的那一张。

牌堆的内容会变（往目录里加图、删图、改台词）：出牌前先和当前清单对一遍——没了的
从 ``queue`` / ``seen`` 里剔掉，新来的随机插进 ``queue``（这一轮就能轮到，但不插队）。

**记在哪**：内存里一份；桌宠启动时 ``attach`` 到配置目录下的 ``shuffle-state.json``
之后，每出一张就把整张表原子写回去（几 KB），所以重启后接着上一轮往下出，不会一
重启就把刚看过的再发一遍。没有 ``attach``（测试、设置进程）就只在内存里。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Iterable, Sequence

log = logging.getLogger(__name__)

STATE_FILE_NAME = "shuffle-state.json"
#: 各副牌的用途名（牌堆键的前半段）
POPUP = "popup"
SELF_TALK_TEXT = "self_talk_text"
SELF_TALK_IMAGE = "self_talk_image"
CLICK_TEXT = "click_text"
#: 最多记这么多副牌；超出时丢掉最久没用的（换过目录 / 改过台词留下的旧牌堆）
MAX_DECKS = 32


class ShuffleStore:
    """若干副牌的状态表（可选落盘）。``rng`` 可注入（测试要确定性）。"""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()
        self._decks: dict[str, dict] = {}
        self._path: Path | None = None

    # ------------------------------------------------------------ 落盘
    def attach(self, path: Path | str) -> None:
        """此后的状态记到 ``path``；文件已存在就先读回来（接着上一轮出）。"""
        self._path = Path(path)
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        decks = raw.get("decks") if isinstance(raw, dict) else None
        if not isinstance(decks, dict):
            return
        for key, deck in decks.items():
            if not isinstance(deck, dict):
                continue
            self._decks[str(key)] = {
                "queue": [str(x) for x in deck.get("queue") or [] if isinstance(x, str)],
                "seen": [str(x) for x in deck.get("seen") or [] if isinstance(x, str)],
                "last": deck.get("last") if isinstance(deck.get("last"), str) else None,
                "used": float(deck.get("used") or 0.0),
            }

    def detach(self) -> None:
        """此后不再落盘（内存里的进度保留）。"""
        self._path = None

    def reset(self) -> None:
        """清空全部状态并断开文件（测试隔离用）。"""
        self._decks.clear()
        self._path = None

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temp = self._path.with_name(f"{self._path.name}.{os.getpid()}.tmp")
            temp.write_text(json.dumps({"version": 1, "decks": self._decks}, ensure_ascii=False),
                            encoding="utf-8")
            os.replace(temp, self._path)
        except OSError:
            log.debug("洗牌状态没写进磁盘（不影响本次运行）", exc_info=True)

    # ------------------------------------------------------------ 出牌
    def draw(self, key: str, items: Iterable[str]) -> str | None:
        """从 ``key`` 这副牌里出一张；``items`` 是它此刻的全部牌面。空牌堆返回 None。"""
        cards = list(dict.fromkeys(str(item) for item in items))
        if not cards:
            return None
        deck = self._decks.setdefault(key, {"queue": [], "seen": [], "last": None, "used": 0.0})
        present = set(cards)
        queue = [card for card in deck["queue"] if card in present]
        seen = [card for card in deck["seen"] if card in present]
        known = set(queue) | set(seen)
        for card in cards:
            if card not in known:      # 新来的：随机插进这一轮剩下的牌里
                queue.insert(self._rng.randint(0, len(queue)), card)
        if not queue:                  # 一轮出完：重新洗牌
            queue = list(cards)
            self._rng.shuffle(queue)
            seen = []
            if len(queue) > 1 and queue[0] == deck["last"]:
                other = self._rng.randrange(1, len(queue))
                queue[0], queue[other] = queue[other], queue[0]
        card = queue.pop(0)
        seen.append(card)
        deck.update(queue=queue, seen=seen, last=card, used=time.time())
        self._prune()
        self._save()
        return card

    def put_back(self, key: str, card: str) -> None:
        """刚出的这张没能显示出来（如配图还没解码好）：放回牌堆顶，下次先出它。"""
        deck = self._decks.get(key)
        card = str(card)
        if deck is None or card not in deck["seen"]:
            return
        deck["seen"].remove(card)
        deck["queue"].insert(0, card)
        if deck["last"] == card:
            deck["last"] = None
        self._save()

    def _prune(self) -> None:
        if len(self._decks) <= MAX_DECKS:
            return
        for key in sorted(self._decks, key=lambda k: self._decks[k]["used"])[:-MAX_DECKS]:
            del self._decks[key]

    def state(self, key: str) -> dict | None:
        """一副牌的当前状态副本（查看 / 测试用）。"""
        deck = self._decks.get(key)
        return None if deck is None else {**deck, "queue": list(deck["queue"]),
                                          "seen": list(deck["seen"])}


#: 进程级状态表。主进程启动时 ``STORE.attach(配置目录 / STATE_FILE_NAME)``。
STORE = ShuffleStore()


def deck_key(purpose: str, items: Sequence) -> str:
    """牌堆的键：图片按所在目录认（换目录 = 换一副牌），台词按内容认。"""
    first = items[0]
    if isinstance(first, Path):
        return f"{purpose}|{first.parent}"
    digest = hashlib.sha1("\n".join(sorted(str(item) for item in items)).encode("utf-8"))
    return f"{purpose}|{digest.hexdigest()[:12]}"


def draw(purpose: str, items: Sequence):
    """从 ``items`` 里洗牌式出一个（图片路径或台词）；空则 None。

    图片在牌堆里按文件名记，所以同一个目录换了盘符 / 安装位置也接得上。
    """
    items = list(items)
    if not items:
        return None
    if isinstance(items[0], Path):
        by_card = {path.name: path for path in items}
    else:
        by_card = {str(item): item for item in items}
    card = STORE.draw(deck_key(purpose, items), list(by_card))
    return by_card.get(card)


def put_back(purpose: str, items: Sequence, item) -> None:
    """``draw`` 出的 ``item`` 没显示成：放回去（见 ``ShuffleStore.put_back``）。"""
    items = list(items)
    if not items:
        return
    card = item.name if isinstance(item, Path) else str(item)
    STORE.put_back(deck_key(purpose, items), card)
