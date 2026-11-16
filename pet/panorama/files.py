# -*- coding: utf-8 -*-
"""文件查看（只读）：配置全景页面能读哪些文件、怎么读。

页面经本机服务来要文件内容，所以这里是一道门：**只有存储表里登记了、又在 ``VIEWABLE`` 里点了名的存储，
它名下的文件才读得到**。一条路径要过四关才会被打开：

1. 那一项存储在 ``VIEWABLE`` 里，种类是内容（``content``），它的根在这台机器上读得到（``ROOTS``）；
2. 路径是一条规规矩矩的相对路径：正斜杠、没有 ``..`` / ``.`` / 空段、不是绝对路径、不带盘符；
3. 按存储表的模式，这条路径**正好属于这一项**（同一个目录下别的存储的文件不算，比如项目目录里的会话原文）；
4. 解开符号链接之后仍然在根目录里面，而且是个普通文件。

哪一关没过都只回一个短代码（``not_viewable`` / ``bad_path`` / ``not_found``），不说为什么，也不带任何内容。

设置文件（``settings.json``、``.claude.json``、``config.json``）不在名单里：里面可能夹着密钥。WSL 里那个家目录
也不在：要经 ``wsl.exe`` 去读，这一步还没做。

**只用标准库、不碰 Qt。** 在本机服务的请求线程上跑。
"""
from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path, PurePosixPath

from .. import data_stores as ds
from .claude_home_probe import BLOCK_RE

#: 能在页面上打开看的存储。加一项之前先确认：它是人或 AI 写的内容，里面不会有密钥。
VIEWABLE = ("claude_md", "claude_memory", "distill_entries", "distill_entries_work")
#: 这台机器上直接读得到的根 → ``Reader`` 里怎么找到它。
ROOTS = ("data", "claude_home")
MAX_BYTES = 512 * 1024      # 一个文件最多给页面这么多；再大就截断并说明
LIST_LIMIT = 500            # 一项存储最多列这么多个文件


class FileError(Exception):
    """读不了。``code`` 给页面看：``not_viewable`` / ``bad_path`` / ``not_found``。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def viewable(store_id: str) -> bool:
    store = _STORES.get(store_id)
    return bool(store) and store_id in VIEWABLE and store.kind == "content" and store.root in ROOTS


_STORES = {store.id: store for store in ds.STORES}


def _stamp(seconds: float) -> str:
    try:
        return dt.datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return ""


def _clean(path: str) -> str:
    """第二关：只收规矩的相对路径，原样返回；否则 ``bad_path``。"""
    text = str(path or "")
    if not text or "\\" in text or "\x00" in text or ":" in text or text.startswith("/") or text.endswith("/"):
        raise FileError("bad_path")
    if any(part in ("", ".", "..") for part in text.split("/")) or PurePosixPath(text).is_absolute():
        raise FileError("bad_path")
    return text


def _label(store: ds.Store, relative: str) -> str:
    """清单里显示的短名字：模式里前几个通配符对上的那几段，加上文件名（``projects/*/memory/*.md`` →
    ``<项目> / <文件名>``）；没有通配符的模式就是文件名。完整路径另外给，页面放在悬停提示里。"""
    name = relative.rsplit("/", 1)[-1]
    for pattern in store.patterns:
        if "*" not in pattern:
            continue
        found = re.fullmatch("(.+)".join(re.escape(piece) for piece in pattern.split("*")), relative)
        if found:
            return " / ".join([*found.groups()[:-1], name])
    return name


def _marks(text: str) -> list[dict]:
    """文本里值得标出来的段落（行号从 1 数，两头都含）。现在只有一种：蒸馏写进 CLAUDE.md 的受管块。"""
    found = BLOCK_RE.search(text)
    if not found:
        return []
    first = text.count("\n", 0, found.start()) + 1
    return [{"from": first, "to": first + text.count("\n", found.start(), found.end()), "kind": "managed"}]


class Reader:
    """绑定了这台机器上两个根目录的读取器：``listing`` 列一项存储名下的文件，``read`` 读其中一个。"""

    def __init__(self, *, config_dir: str | Path, home: str | Path) -> None:
        self._roots = {"data": Path(config_dir), "claude_home": Path(home) / ".claude"}

    def _store(self, store_id: str) -> tuple[ds.Store, Path]:
        if not viewable(store_id):
            raise FileError("not_viewable")
        store = _STORES[store_id]
        return store, self._roots[store.root]

    @staticmethod
    def _inside(root: Path, relative: str) -> Path | None:
        """第四关：解开链接后的真实路径；跑到根外面去了、或者不是普通文件，返回 ``None``。"""
        try:
            real_root = root.resolve(strict=True)
            real = (root / relative).resolve(strict=True)
        except (OSError, RuntimeError):
            return None
        return real if real.is_file() and real_root in real.parents else None

    def listing(self, store_id: str) -> dict:
        """这一项存储名下、这台机器上此刻有的文件（按路径排序，最多 ``LIST_LIMIT`` 个）。"""
        store, root = self._store(store_id)
        found: list[dict] = []
        for start in sorted({pattern.split("*", 1)[0].rsplit("/", 1)[0] if "/" in pattern.split("*", 1)[0] else ""
                             for pattern in store.patterns if "*" in pattern}):
            stack = [str(root / start) if start else str(root)]
            while stack:
                try:
                    entries = sorted(os.scandir(stack.pop()), key=lambda entry: entry.name)
                except OSError:
                    continue
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                        continue
                    relative = os.path.relpath(entry.path, root).replace(os.sep, "/")
                    if ds.match(store.root, relative) is store:
                        found.append({"path": relative})
        found += [{"path": pattern} for pattern in store.patterns if "*" not in pattern]
        files = []
        for item in sorted({f["path"]: f for f in found}.values(), key=lambda f: f["path"]):
            real = self._inside(root, item["path"])
            if real is None:
                continue
            stat = real.stat()
            files.append({"path": item["path"], "label": _label(store, item["path"]), "bytes": stat.st_size,
                          "mtime": _stamp(stat.st_mtime)})
        return {"store": store_id, "files": files[:LIST_LIMIT], "truncated": len(files) > LIST_LIMIT}

    def read(self, store_id: str, path: str) -> dict:
        """读一个文件的文本（最多 ``MAX_BYTES``，不是 UTF-8 的字节换成替代符）。"""
        store, root = self._store(store_id)
        relative = _clean(path)
        if ds.match(store.root, relative) is not store:
            raise FileError("bad_path")
        if not (root / relative).exists():
            raise FileError("not_found")
        real = self._inside(root, relative)
        if real is None:
            raise FileError("bad_path")
        try:
            stat = real.stat()
            with open(real, "rb") as handle:
                raw = handle.read(MAX_BYTES + 1)
        except OSError:
            raise FileError("not_found") from None
        text = raw[:MAX_BYTES].decode("utf-8", "replace")
        return {"store": store_id, "path": relative, "text": text, "bytes": stat.st_size, "mtime": _stamp(stat.st_mtime),
                "truncated": len(raw) > MAX_BYTES, "marks": _marks(text)}
