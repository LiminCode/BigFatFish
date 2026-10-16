# -*- coding: utf-8 -*-
"""本地知识库：把一个 GitHub 仓库同步成本地副本，对话时只从本地读。

为什么是本地副本而不是每次去 GitHub 现查（那是 ``connectors.py`` 的 GitHub 连接器）：
连接器每条消息都要带约 1.2 万 token 的工具定义，读文件还要绕 GitHub 的 MCP 服务器；
本地副本只需要三个很小的工具，读的是磁盘。

三件事都在这里，且都不依赖 Qt：

- **同步** ``sync``：下载仓库默认分支的 zip 包（不依赖本机装没装 git，Token 只出现在
  请求头里），只解出文本类文件，整目录原子替换。状态写在 ``state.json``，设置窗口
  （独立进程）和肥鱼主进程都读它。
- **读取** ``KnowledgeBase``：list / read / search，路径一律限制在副本目录内。
- **工具** ``toolset_for``：把上面三样包装成 Claude 通道的客户端工具，连同一段用法
  说明交给 ``AnthropicProvider``。

定时同步在 ``knowledge_sync.py``（那里才有 Qt）。
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from . import models as _models
from .anthropic_provider import uses_anthropic
from .connectors import GITHUB_TOKEN_REF
from ..i18n import t

DIR_NAME = "knowledge-base"
SYNC_INTERVAL_S = 24 * 3600
#: 同步失败后隔多久再试（不等到明天，也不每个检查周期都打一次 GitHub）
RETRY_AFTER_FAILURE_S = 30 * 60

TEXT_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".rst", ".org", ".csv", ".json", ".yaml", ".yml"})
_MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_FILES = 20_000
_READ_CHARS = 40_000
_LIST_ENTRIES = 300
_SEARCH_HITS = 30
_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")


class KnowledgeBaseError(Exception):
    pass


# ---------------------------------------------------------------- 仓库与目录

def parse_repo(text: str) -> str:
    """``owner/repo``、仓库网址、带 ``.git`` 的克隆地址 → ``owner/repo``；认不出返回空串。"""
    value = str(text or "").strip()
    value = re.sub(r"^(https?://)?(www\.)?github\.com[/:]", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^git@github\.com:", "", value, flags=re.IGNORECASE)
    value = "/".join(value.strip("/").split("/")[:2])
    if value.endswith(".git"):
        value = value[:-4]
    return value if _REPO_RE.match(value) and not value.endswith("/.") else ""


def base_dir(config_dir) -> Path:
    return Path(config_dir) / DIR_NAME


def content_dir(config_dir) -> Path:
    return base_dir(config_dir) / "current"


@dataclass
class SyncState:
    repo: str = ""            # 当前副本来自哪个仓库
    synced_at: float = 0.0    # 当前副本的同步时间（Unix 秒）；0 = 没有副本
    files: int = 0
    bytes: int = 0
    attempted_at: float = 0.0  # 最近一次尝试（成功或失败）
    attempted_repo: str = ""
    error: str = ""            # 最近一次尝试的失败原因；成功后清空


def load_state(config_dir) -> SyncState:
    try:
        raw = json.loads((base_dir(config_dir) / "state.json").read_text(encoding="utf-8"))
        return SyncState(**{k: raw[k] for k in SyncState.__dataclass_fields__ if k in raw})
    except (OSError, ValueError, TypeError):
        return SyncState()


def _save_state(config_dir, state: SyncState) -> None:
    root = base_dir(config_dir)
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f"state.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(asdict(state), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, root / "state.json")


def has_copy(config_dir, repo: str) -> bool:
    state = load_state(config_dir)
    return bool(repo) and state.repo == repo and state.synced_at > 0 and content_dir(config_dir).is_dir()


def needs_sync(config_dir, repo: str, now: float | None = None) -> bool:
    """该不该现在同步：没有这个仓库的副本，或副本超过一天；刚失败过则先等一阵。"""
    if not repo:
        return False
    now = time.time() if now is None else now
    state = load_state(config_dir)
    if state.error and state.attempted_repo == repo and now - state.attempted_at < RETRY_AFTER_FAILURE_S:
        return False
    return not has_copy(config_dir, repo) or now - state.synced_at >= SYNC_INTERVAL_S


def describe(config_dir, repo: str) -> str:
    """给设置页看的一句话状态。"""
    state = load_state(config_dir)
    if state.error and state.attempted_repo == repo:
        return t("settings.ai.kb_failed", error=state.error)
    if has_copy(config_dir, repo):
        when = datetime.fromtimestamp(state.synced_at).strftime("%Y-%m-%d %H:%M")
        return t("settings.ai.kb_synced", when=when, files=state.files)
    return t("settings.ai.kb_never")


# ---------------------------------------------------------------- 同步

def _download(url: str, headers: dict[str, str], timeout: float = 60.0) -> bytes:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:   # noqa: S310 - 固定的 https 地址
        chunks, total = [], 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            total += len(chunk)
            if total > _MAX_DOWNLOAD_BYTES:
                raise KnowledgeBaseError("仓库压缩包超过 200 MB，不适合当知识库")
            chunks.append(chunk)


def _safe_member(name: str) -> PurePosixPath | None:
    """zip 条目 → 副本内的相对路径；不该解出来的返回 None。

    去掉 GitHub 加的顶层目录（``owner-repo-sha/``）；拒绝往上跳、绝对路径、带盘符或
    冒号的名字；跳过点开头的目录和文件（``.obsidian``、``.git`` 之类）与非文本类型。
    """
    parts = PurePosixPath(name.replace("\\", "/")).parts[1:]
    if not parts or any(p in ("", ".", "..") or p.startswith(".") or ":" in p for p in parts):
        return None
    path = PurePosixPath(*parts)
    return path if path.suffix.lower() in TEXT_SUFFIXES else None


def _extract(archive: bytes, dest: Path) -> tuple[int, int]:
    files = size = 0
    try:
        bundle = zipfile.ZipFile(io.BytesIO(archive))
    except zipfile.BadZipFile as exc:
        raise KnowledgeBaseError("下载到的不是有效的 zip 包") from exc
    with bundle:
        for info in bundle.infolist():
            if info.is_dir() or info.file_size > _MAX_FILE_BYTES:
                continue
            relative = _safe_member(info.filename)
            if relative is None:
                continue
            if files >= _MAX_FILES:
                break
            target = dest.joinpath(*relative.parts)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.read(info))
            except OSError:
                continue          # 路径过长等单个文件的问题不该废掉整次同步
            files += 1
            size += info.file_size
    return files, size


def _http_error_text(exc: urllib.error.HTTPError, repo: str, has_token: bool) -> str:
    if exc.code == 404:
        hint = "检查仓库名" if has_token else "私有仓库需要先在「连接器」里填 GitHub Token"
        return f"找不到仓库 {repo}（{hint}）"
    if exc.code in (401, 403):
        return f"GitHub 拒绝访问（HTTP {exc.code}）：Token 无效、过期或没有这个仓库的读权限"
    return f"GitHub 返回 HTTP {exc.code}"


def sync(config_dir, repo: str, token: str = "", *, fetch: Callable[[str, dict], bytes] | None = None,
         now: float | None = None) -> SyncState:
    """同步一次。成功返回新状态；失败把原因记进 ``state.json`` 后抛 ``KnowledgeBaseError``，
    已有的副本原样保留。"""
    repo = parse_repo(repo)
    if not repo:
        raise KnowledgeBaseError("仓库写成 owner/repo 或 GitHub 网址")
    now = time.time() if now is None else now
    token = str(token or "").strip()
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "BigFatFish-knowledge-base"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    root = base_dir(config_dir)
    incoming = root / f"incoming-{os.getpid()}"
    previous = load_state(config_dir)
    try:
        try:
            archive = (fetch or _download)(f"https://api.github.com/repos/{repo}/zipball", headers)
        except urllib.error.HTTPError as exc:
            raise KnowledgeBaseError(_http_error_text(exc, repo, bool(token))) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise KnowledgeBaseError(f"网络错误：{getattr(exc, 'reason', exc)}") from exc
        shutil.rmtree(incoming, ignore_errors=True)
        incoming.mkdir(parents=True, exist_ok=True)
        files, size = _extract(archive, incoming)
        if not files:
            raise KnowledgeBaseError("仓库里没有可读的文本文件（.md / .txt 等）")
        current, retired = root / "current", root / f"retired-{os.getpid()}"
        shutil.rmtree(retired, ignore_errors=True)
        if current.exists():
            os.replace(current, retired)
        os.replace(incoming, current)
        shutil.rmtree(retired, ignore_errors=True)
    except KnowledgeBaseError as exc:
        shutil.rmtree(incoming, ignore_errors=True)
        previous.attempted_at, previous.attempted_repo, previous.error = now, repo, str(exc)
        _save_state(config_dir, previous)
        raise
    except OSError as exc:
        shutil.rmtree(incoming, ignore_errors=True)
        previous.attempted_at, previous.attempted_repo, previous.error = now, repo, f"写入本地副本失败：{exc}"
        _save_state(config_dir, previous)
        raise KnowledgeBaseError(previous.error) from exc
    state = SyncState(repo=repo, synced_at=now, files=files, bytes=size, attempted_at=now, attempted_repo=repo)
    _save_state(config_dir, state)
    return state


def stored_token() -> str:
    """同步私有仓库用的 Token：与 GitHub 连接器共用钥匙串里的那一个。"""
    return _models.SecretStore().get(GITHUB_TOKEN_REF).strip()


# ---------------------------------------------------------------- 读取

class KnowledgeBase:
    """副本目录上的只读访问；所有路径都落在 ``root`` 之内。"""

    def __init__(self, root) -> None:
        self.root = Path(root)

    def _resolve(self, path: str) -> Path:
        relative = str(path or "").replace("\\", "/").strip().strip("/")
        target = (self.root / relative).resolve()
        root = self.root.resolve()
        if target != root and root not in target.parents:
            raise KnowledgeBaseError("路径超出了知识库目录")
        return target

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root.resolve()).as_posix()

    def _files(self):
        root = self.root.resolve()
        for directory, _dirs, names in os.walk(root):
            for name in sorted(names):
                yield Path(directory) / name

    def list(self, path: str = "") -> str:
        target = self._resolve(path)
        if not target.is_dir():
            raise KnowledgeBaseError(f"没有这个目录：{path or '/'}")
        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        lines = [f"{p.name}/" if p.is_dir() else f"{p.name}  ({p.stat().st_size} 字节)" for p in entries[:_LIST_ENTRIES]]
        if len(entries) > _LIST_ENTRIES:
            lines.append(f"……还有 {len(entries) - _LIST_ENTRIES} 项没列出")
        return "\n".join(lines) or "（空目录）"

    def read(self, path: str) -> str:
        target = self._resolve(path)
        if not target.is_file():
            raise KnowledgeBaseError(f"没有这个文件：{path}（用 kb_list 看目录，或用 kb_search 搜）")
        text = target.read_text(encoding="utf-8", errors="replace")
        if len(text) > _READ_CHARS:
            return text[:_READ_CHARS] + f"\n\n……（文件共 {len(text)} 字，只给出前 {_READ_CHARS} 字）"
        return text

    def search(self, query: str) -> str:
        needle = str(query or "").strip().lower()
        if not needle:
            raise KnowledgeBaseError("搜索词不能为空")
        hits: list[str] = []
        for file in self._files():
            relative = self._relative(file)
            if needle in relative.lower():
                hits.append(f"{relative}  （文件名匹配）")
            try:
                lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for number, line in enumerate(lines, 1):
                if needle in line.lower():
                    hits.append(f"{relative}:{number}: {line.strip()[:200]}")
                    if len(hits) >= _SEARCH_HITS:
                        return "\n".join(hits) + f"\n……（只给出前 {_SEARCH_HITS} 处，换更具体的词）"
        return "\n".join(hits) or f"没有找到「{query}」"


# ---------------------------------------------------------------- 工具（Claude 通道）

def _tool(name: str, description: str, field: str, field_description: str, required: bool) -> dict:
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "additionalProperties": False,
                             "properties": {field: {"type": "string", "description": field_description}},
                             "required": [field] if required else []}}


TOOL_DEFINITIONS = [
    _tool("kb_read", "读取用户知识库里的一个文件，返回全文（很长时截断）。", "path",
          "相对知识库根目录的路径，例如 INDEX.md 或 2-Projects/某项目/笔记.md", True),
    _tool("kb_list", "列出用户知识库里某个目录下的文件和子目录。", "path",
          "相对知识库根目录的目录路径；留空表示根目录", False),
    _tool("kb_search", "在用户知识库的文件名和正文里搜一个词（不分大小写），返回匹配的文件与行。", "query",
          "要找的词或短语", True),
]


class KnowledgeToolset:
    """交给 ``AnthropicProvider`` 的客户端工具：定义、用法说明、执行入口。"""

    def __init__(self, root, repo: str, synced_at: float) -> None:
        self.definitions = TOOL_DEFINITIONS
        self._kb = KnowledgeBase(root)
        when = datetime.fromtimestamp(synced_at).strftime("%Y-%m-%d %H:%M") if synced_at else "未知"
        self.system_note = (
            "## 用户的知识库\n"
            f"用户的个人知识库（GitHub 仓库 {repo}）在本地有一份副本，最近同步于 {when}。"
            "问题涉及用户本人的生活、工作、项目、决定或偏好时，先查它再回答："
            "第一步用 kb_read 读根目录的 INDEX.md（没有就读 README.md，再没有就 kb_list 看根目录），它是地图；"
            "然后按地图读具体笔记，找不到再用 kb_search。闲聊时不需要查。"
            "副本里的内容截至同步时间，之后的变化你不知道；引用带日期的事情时注意它可能已经过时。"
            "不要复述其中的密码、密钥或登录凭据。"
        )

    def run(self, name: str, tool_input: Any) -> str:
        args = tool_input if isinstance(tool_input, dict) else {}
        if name == "kb_read":
            return self._kb.read(str(args.get("path") or ""))
        if name == "kb_list":
            return self._kb.list(str(args.get("path") or ""))
        if name == "kb_search":
            return self._kb.search(str(args.get("query") or ""))
        raise KnowledgeBaseError(f"没有这个工具：{name}")


def toolset_for(settings, provider, config_dir) -> KnowledgeToolset | None:
    """这次对话要不要带知识库工具：开关开着、走 Claude 通道、且本地已有这个仓库的副本。"""
    if not getattr(settings, "knowledge_base_enabled", False) or not uses_anthropic(provider):
        return None
    repo = parse_repo(getattr(settings, "knowledge_base_repo", ""))
    if not has_copy(config_dir, repo):
        return None
    return KnowledgeToolset(content_dir(config_dir), repo, load_state(config_dir).synced_at)
