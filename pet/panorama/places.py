# -*- coding: utf-8 -*-
"""存储表里的东西画在图上哪里。

存储表（``pet/data_stores.py``）有几十项，一项一块磁贴图就没法看了。所以按「地方」归拢：一个地方是一个或几个
根（``data_stores.ROOTS``），画在某个分区的某一列；这个地方里的存储再按「硬盘没了会怎样」分成最多三块磁贴
（``data_stores.STANDINGS``：进了仓库 / 只在这台机器 / 丢了不要紧），每块点开列出里面的每一项。

**存储表里加了一个新的根 = 在这里说它画在哪**，否则 ``tests/test_panorama_storage.py`` 会红。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Place:
    id: str                     # 磁贴标识的中段：st_<id>_<standing>
    roots: tuple[str, ...]      # 归到这个地方的根；第一个是「打开所在位置」去的那个
    region: str                 # 画在哪个分区
    col: int                    # 那个分区的第几列
    owner: str                  # 谁往这里写：图上的一个节点，存储线从它出发
    label: str                  # 这个地方叫什么：文案键 panorama.place.<label>
    wsl: bool = False           # 在 WSL 那一侧：那半张图探完才画


PLACES: tuple[Place, ...] = (
    Place("fish", ("data", "keyring", "os"), "win", 1, "pet", "fish"),
    Place("cc_win", ("claude_home", "home"), "win", 0, "cc_win", "claude_win"),
    Place("cc_wsl", ("claude_home_wsl",), "wsl", 1, "cc_wsl", "claude_wsl", wsl=True),
)

#: 图上本来就有一块磁贴代表它的存储（两个知识库的克隆）：不再进分组磁贴，只在那块磁贴上补一句「丢了从哪恢复」。
OWN_TILE = {"kb_personal_repo": "vault_personal", "kb_work_repo": "vault_work"}

#: 列在分组磁贴里、图上另有一块磁贴也代表它的：那块磁贴上也补一句，免得用户点了 CLAUDE.md 却看不到这个答案。
ALSO_ON = {
    "config": "pet",
    "claude_settings": "set_win", "claude_md": "md_win", "claude_memory": "mem_win", "claude_plugins": "plug_win",
    "claude_settings_wsl": "set_wsl", "claude_md_wsl": "md_wsl", "claude_memory_wsl": "mem_wsl", "claude_plugins_wsl": "plug_wsl",
}
