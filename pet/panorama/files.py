# -*- coding: utf-8 -*-
"""文件查看（只读）：配置全景页面能读哪些文件、怎么读。

页面经本机服务来要文件内容，所以这里是一道门：**只有存储表里登记了、又在 ``VIEWABLE`` 里点了名的存储，
它名下的文件才读得到**。一条路径要过四关才会被打开：

1. 那一项存储在 ``VIEWABLE`` 里，种类不是登录凭据或密钥（``NEVER``），它的根在这台机器上读得到（``ROOTS``）；
2. 路径是一条规规矩矩的相对路径：正斜杠、没有 ``..`` / ``.`` / 空段、不是绝对路径、不带盘符；
3. 按存储表的模式，这条路径**正好属于这一项**（同一个目录下别的存储的文件不算，比如项目目录里的会话原文）；
4. 路径上**不经过任何符号链接或目录联接**，而且是个普通文件。解开链接后的真实位置必须正好是「根 + 这条路径」：
   只查「还在根里面」不够——根里面的一个链接可以让一条看着属于「项目记忆」的路径，真身落在登录凭据上。

哪一关没过都只回一个短代码（``not_viewable`` / ``bad_path`` / ``not_found``），不说为什么，也不带任何内容。

**名单里的文件原样给，不脱敏**（用户 2026-11-16 定的：能打开这个页面的只有本人，设置文件、JSON 文件直接看原文）。
所以 ``settings.json``、``.claude.json``、``config.json`` 都在名单里，哪怕里面夹着密钥。这道门守的是范围，不是内容：
名单外的、根目录外的，一个字也拿不到。

两样东西永远不在名单里，``viewable()`` 按种类再拦一次：登录凭据（``.credentials.json``）和钥匙串——
看它们的原文没有用处，万一截图或投屏却会泄漏。不是文字的东西（图片、音效、语音缓存）、会话原文、日志、缓存也不在：
前者显示不了，后者量大，要看再加。

WSL 里那个家目录的文件（``claude_home_wsl``）经 ``wsl.exe`` 去读：前三关照旧在这边过，过不了的根本不会起进程；
第四关只有在 WSL 里面才守得了，由 ``wsl_file_agent`` 守。构造 ``Reader`` 时没给 ``run_wsl`` 的话，那一侧的存储读不了。

**只用标准库、不碰 Qt**（怎么起 ``wsl.exe`` 由调用方传进来）。在本机服务的请求线程上跑。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path, PurePosixPath

from .. import data_stores as ds
from . import wsl_file_agent
from .claude_home_probe import BLOCK_RE

#: 能在页面上打开看的存储：设置、人和 AI 写的文字内容、JSON 簿记。加一项之前先确认它是文字。
VIEWABLE = (
    # 设置
    "config", "config_slots", "claude_settings", "claude_json",
    # 人和 AI 写的内容
    "claude_md", "claude_memory", "claude_skills", "distill_entries", "distill_entries_work", "distill_proposals",
    "chat_sessions", "todo_items", "message_log",
    # 簿记
    "session_history", "config_backup_state", "distill_state", "assistant_state", "work_state",
    # 运行记录：种类是日志，但一次运行只有一行元数据（没有正文），量小；瀑布流页做出来之前在这里看
    "run_journal",
    # WSL 里公司 Claude Code 的家目录（经 wsl.exe 读）
    "claude_settings_wsl", "claude_md_wsl", "claude_memory_wsl", "claude_skills_wsl",
)
#: 不管名单怎么写都不给看的种类。
NEVER = ("secret", "login")
#: 读得到的根。``home`` 不会被走一遍：那个根下只有模式里写了确切名字的文件。``claude_home_wsl`` 在 WSL 里。
ROOTS = ("data", "claude_home", "home", "claude_home_wsl")
WSL_ROOT = "claude_home_wsl"
WSL_TIMEOUT_S = 20.0        # 一次去 WSL 里列 / 读，最多等这么久（发行版冷启动要几秒）
WSL_CANDIDATES = 20_000     # 让 WSL 那边最多报这么多个候选文件，这边再按存储表筛
BINARY_PROBE = 8192         # 开头这么多字节里有 NUL 就当它不是文字
MAX_BYTES = 512 * 1024      # 一个文件最多给页面这么多；再大就截断并说明
LIST_LIMIT = 500            # 一项存储最多列这么多个文件


class FileError(Exception):
    """读不了。``code`` 给页面看：``not_viewable`` / ``bad_path`` / ``not_found`` / ``unavailable``（WSL 没回话）。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def viewable(store_id: str) -> bool:
    store = _STORES.get(store_id)
    return bool(store) and store_id in VIEWABLE and store.kind not in NEVER and store.root in ROOTS


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
    """绑定了几个根目录的读取器：``listing`` 列一项存储名下的文件，``read`` 读其中一个。

    ``run_wsl`` 是「在默认发行版里跑一条命令」的函数（``claude_hooks.run_wsl`` 那个样子）；不给就读不了 WSL 一侧。
    """

    def __init__(self, *, config_dir: str | Path, home: str | Path, run_wsl=None) -> None:
        self._roots = {"data": Path(config_dir), "claude_home": Path(home) / ".claude", "home": Path(home)}
        self._run_wsl = run_wsl

    def _store(self, store_id: str) -> tuple[ds.Store, Path | None]:
        if not viewable(store_id):
            raise FileError("not_viewable")
        store = _STORES[store_id]
        if store.root == WSL_ROOT:
            if self._run_wsl is None:
                raise FileError("not_viewable")
            return store, None
        return store, self._roots[store.root]

    def _ask_wsl(self, request: dict) -> dict:
        """让 WSL 里的 ``wsl_file_agent`` 办一件事。请求写成源码里的一个字符串字面量，不经过命令行。"""
        source = Path(wsl_file_agent.__file__).read_text(encoding="utf-8") + f"\nagent_main({json.dumps(request)!r})\n"
        try:
            code, out = self._run_wsl(["-e", "python3", "-"], input_text=source, timeout=WSL_TIMEOUT_S)
            start = out.find("{")
            answer = json.loads(out[start:]) if code == 0 and start >= 0 else None
        except Exception:  # noqa: BLE001 - 起不来、超时、回的不是 JSON：对页面都是「那边没回话」
            answer = None
        if not isinstance(answer, dict):
            raise FileError("unavailable")
        if answer.get("error"):
            raise FileError(answer["error"] if answer["error"] in ("not_found", "bad_path") else "unavailable")
        return answer

    @staticmethod
    def _starts(store: ds.Store) -> list[str]:
        """这一项的文件可能在哪些子目录下：每条带通配符的模式里，第一个通配符之前的那段目录（空串 = 根）。"""
        return sorted({pattern.split("*", 1)[0].rsplit("/", 1)[0] if "/" in pattern.split("*", 1)[0] else ""
                       for pattern in store.patterns if "*" in pattern})

    @staticmethod
    def _inside(root: Path, relative: str) -> Path | None:
        """第四关：解开链接后的真实路径。它必须正好是「根 + 这条相对路径」——路径上经过了链接（不管绕到根外面
        还是根里面别的地方）、或者不是普通文件，返回 ``None``。"""
        try:
            real_root = root.resolve(strict=True)
            real = (root / relative).resolve(strict=True)
            straight = real.relative_to(real_root).as_posix() == relative
        except (OSError, RuntimeError, ValueError):
            return None
        return real if straight and real.is_file() else None

    def listing(self, store_id: str) -> dict:
        """这一项存储名下、这台机器上此刻有的文件（按路径排序，最多 ``LIST_LIMIT`` 个）。"""
        store, root = self._store(store_id)
        if root is None:                                        # WSL 一侧：那边报候选，这边按存储表筛
            answer = self._ask_wsl({"op": "list", "starts": self._starts(store), "limit": WSL_CANDIDATES,
                                    "names": [pattern for pattern in store.patterns if "*" not in pattern]})
            mine = [{"path": f["path"], "label": _label(store, f["path"]), "bytes": f.get("bytes", 0), "mtime": f.get("mtime", "")}
                    for f in answer.get("files") or [] if ds.match(store.root, str(f.get("path") or "")) is store]
            return {"store": store_id, "files": mine[:LIST_LIMIT], "truncated": len(mine) > LIST_LIMIT or bool(answer.get("truncated"))}
        found: list[dict] = []
        for start in self._starts(store):
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
        """读一个文件的文本，原样（最多 ``MAX_BYTES``，不是 UTF-8 的字节换成替代符）。不是文字的文件只说它不是。"""
        store, root = self._store(store_id)
        relative = _clean(path)
        if ds.match(store.root, relative) is not store:
            raise FileError("bad_path")
        if root is None:                                        # WSL 一侧：前三关过了才起进程，第四关在那边
            answer = self._ask_wsl({"op": "read", "path": relative, "max": MAX_BYTES})
            text = str(answer.get("text") or "")
            return {"store": store_id, "path": relative, "text": text, "bytes": answer.get("bytes", 0), "mtime": answer.get("mtime", ""),
                    "truncated": bool(answer.get("truncated")), "binary": bool(answer.get("binary")), "marks": _marks(text)}
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
        binary = b"\x00" in raw[:BINARY_PROBE]
        text = "" if binary else raw[:MAX_BYTES].decode("utf-8", "replace")
        return {"store": store_id, "path": relative, "text": text, "bytes": stat.st_size, "mtime": _stamp(stat.st_mtime),
                "truncated": not binary and len(raw) > MAX_BYTES, "binary": binary, "marks": _marks(text)}
