# -*- coding: utf-8 -*-
"""配置备份到 GitHub：把 ``config.json`` 整份存进用户自己的（私有）仓库，坏了能拉回来。

2026-11-13 实机事故：蓝屏把 config.json 写成全零，桌宠按默认值重建，设置全丢。
PR #40 加了本机的 ``config.json.bak``；这里是机器外的一层：

- **备份** ``backup``：读盘上那份配置（必须是完好的 JSON 对象——坏文件绝不上传，免得
  顶掉 GitHub 上的好备份），经 GitHub Contents API 写进 ``repo`` 的 ``path``；内容
  与远端一样就不提交。Token 只出现在请求头里。
- **恢复** ``restore``：拉回远端那份，校验是配置对象后刷盘写回；写之前把当前文件留作
  ``config.json.before-restore``。
- **启动兜底** ``recover_at_startup``：``Config`` 构造时 config.json 和 ``.bak`` 都坏了，
  就按状态文件里记的仓库 / 路径去拉一次（短超时）。拉不到才用默认值，并在状态文件里
  记下 ``rebuilt_at``：自动备份暂停，免得第二天把一份默认配置推上去顶掉好备份；手动
  备份或恢复成功才解除。
- **该不该自动备份** ``needs_backup``：距上次成功备份满一天、且设置真的变了（只挪了
  位置不算）。失败后隔 ``RETRY_AFTER_FAILURE_S`` 再试。

备份里没有密钥：``Config.save`` 写盘前就把 api_key 剥掉了（密钥在系统钥匙串）。但有
本机路径、服务商地址这类个人信息，所以仓库必须是用户自己的私有仓库——默认跟知识库
同一个（``chat.knowledge_base_repo``），设置里可以另填。

状态写在配置目录的 ``config-backup-state.json``，不放进 config.json：config.json 坏掉
的时候还得知道去哪儿拉备份。定时器在 ``config_backup_sync.py``（那里才有 Qt）。
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable

from .i18n import t

log = logging.getLogger(__name__)

#: 默认存放路径。点开头：Obsidian 不显示，肥鱼自己的知识库同步也跳过它
DEFAULT_PATH = ".big-fat-fish/config.json"
STATE_FILE = "config-backup-state.json"
BACKUP_INTERVAL_S = 24 * 3600
RETRY_AFTER_FAILURE_S = 30 * 60
REQUEST_TIMEOUT_S = 20.0
#: 启动兜底时的超时：只在 config.json 与 .bak 都坏了才会走到，宁可短一点也别卡住启动
STARTUP_FETCH_TIMEOUT_S = 8.0
#: 拖动 / 换屏就会变的键：判断「设置变没变」时不算
VOLATILE_KEYS = ("rx", "ry", "screen_name", "facing")
_API = "https://api.github.com"

#: (method, url, headers, body, timeout) -> (HTTP 状态码, 响应体)
Request = Callable[[str, str, dict, "bytes | None", float], "tuple[int, bytes]"]


class ConfigBackupError(Exception):
    pass


# ---------------------------------------------------------------- 设置

def clean_path(text) -> str:
    """仓库里的文件路径：反斜杠转正斜杠、去首尾斜杠；空的或带 ``..`` 的回默认路径。"""
    value = str(text or "").replace("\\", "/").strip().strip("/")
    parts = PurePosixPath(value).parts if value else ()
    if not parts or any(p in ("", ".", "..") for p in parts):
        return DEFAULT_PATH
    return "/".join(parts)


_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")


def _parse_repo(text) -> str:
    """``owner/repo``、仓库网址、克隆地址 → ``owner/repo``；认不出返回空串。

    与 ``chat.knowledge_base.parse_repo`` 同一套规则，抄一份是因为 ``Config`` 构造时就要
    归一化这一节，而那个模块顶层会拉起聊天 / SDK 依赖，不该进启动路径。
    """
    value = str(text or "").strip()
    value = re.sub(r"^(https?://)?(www\.)?github\.com[/:]", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^git@github\.com:", "", value, flags=re.IGNORECASE)
    value = "/".join(value.strip("/").split("/")[:2])
    if value.endswith(".git"):
        value = value[:-4]
    return value if _REPO_RE.match(value) and not value.endswith("/.") else ""


def normalize(value) -> dict:
    data = value if isinstance(value, dict) else {}
    auto = data.get("auto", False)
    if isinstance(auto, str):
        auto = auto.strip().lower() in ("1", "true", "yes", "on")
    return {"auto": bool(auto), "repo": _parse_repo(data.get("repo")), "path": clean_path(data.get("path"))}


def target_repo(settings: dict, kb_repo: str = "") -> str:
    """备份去哪个仓库：设置里填了就用它，没填就跟知识库同一个仓库。"""
    return _parse_repo(settings.get("repo")) or _parse_repo(kb_repo)


def stored_token() -> str:
    """钥匙串里的 GitHub Token（与知识库同步 / 连接器共用）。"""
    try:
        from .chat.knowledge_base import stored_token as _token
    except Exception:  # noqa: BLE001 - 不带聊天的打包变体
        return ""
    try:
        return str(_token() or "").strip()
    except Exception:  # noqa: BLE001 - 钥匙串不可用
        return ""


# ---------------------------------------------------------------- 状态文件

@dataclass
class BackupState:
    repo: str = ""
    path: str = ""
    backed_up_at: float = 0.0
    fingerprint: str = ""
    attempted_at: float = 0.0
    error: str = ""
    #: 配置被按默认值重建的时间；非零时自动备份暂停
    rebuilt_at: float = 0.0


def state_path(config_dir) -> Path:
    return Path(config_dir) / STATE_FILE


def load_state(config_dir) -> BackupState:
    try:
        raw = json.loads(state_path(config_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return BackupState()
    if not isinstance(raw, dict):
        return BackupState()
    state = BackupState()
    for f in fields(BackupState):
        value = raw.get(f.name)
        if isinstance(value, type(getattr(state, f.name))) or (f.type == "float" and isinstance(value, int)):
            setattr(state, f.name, value)
    return state


def _save_state(config_dir, state: BackupState) -> None:
    from .config import _write_durably

    try:
        Path(config_dir).mkdir(parents=True, exist_ok=True)
        _write_durably(state_path(config_dir), json.dumps(asdict(state), ensure_ascii=False, indent=2).encode("utf-8"))
    except OSError as exc:
        log.warning("写配置备份状态失败: %s", exc)


def mark_rebuilt(config_dir, now: float | None = None) -> bool:
    """配置按默认值重建了：有备份记录时记下来（暂停自动备份）。返回是否记了。"""
    state = load_state(config_dir)
    if not state.repo:
        return False
    state.rebuilt_at = time.time() if now is None else now
    _save_state(config_dir, state)
    return True


def fingerprint(data: bytes) -> str:
    """配置内容的指纹：去掉位置类易变键、键排序后求 sha256。"""
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return ""
    if not isinstance(raw, dict):
        return ""
    for key in VOLATILE_KEYS:
        raw.pop(key, None)
    return hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def needs_backup(config_dir, config_path, now: float) -> bool:
    state = load_state(config_dir)
    if state.rebuilt_at:
        return False
    if state.error and now - state.attempted_at < RETRY_AFTER_FAILURE_S:
        return False
    if state.fingerprint and now - state.backed_up_at < BACKUP_INTERVAL_S:   # 有指纹 = 备份过
        return False
    try:
        current = fingerprint(Path(config_path).read_bytes())
    except OSError:
        return False
    return bool(current) and current != state.fingerprint


def describe(config_dir) -> str:
    """设置页状态行的文字。"""
    state = load_state(config_dir)
    if state.rebuilt_at:
        return t("config_backup.status_paused")
    parts = []
    if state.backed_up_at:
        when = datetime.fromtimestamp(state.backed_up_at).strftime("%Y-%m-%d %H:%M")
        parts.append(t("config_backup.status_last", when=when, repo=state.repo, path=state.path))
    else:
        parts.append(t("config_backup.status_never"))
    if state.error and state.attempted_at >= state.backed_up_at:
        parts.append(t("config_backup.status_failed", error=state.error))
    return " ".join(parts)


# ---------------------------------------------------------------- GitHub

def _default_request(method: str, url: str, headers: dict, body: bytes | None, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read() or b""


def _contents_url(repo: str, path: str) -> str:
    return f"{_API}/repos/{repo}/contents/{urllib.parse.quote(path)}"


def _call(method: str, repo: str, path: str, token: str, body: dict | None, *, request: Request | None,
          timeout: float) -> tuple[int, dict]:
    if not repo:
        raise ConfigBackupError(t("config_backup.no_repo"))
    if not token:
        raise ConfigBackupError(t("config_backup.no_token"))
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "BigFatFish-config-backup",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    try:
        status, raw = (request or _default_request)(method, _contents_url(repo, path), headers, data, timeout)
    except (urllib.error.URLError, OSError) as exc:
        raise ConfigBackupError(t("config_backup.network_error", error=getattr(exc, "reason", exc))) from exc
    if status in (401, 403):
        raise ConfigBackupError(t("config_backup.denied", code=status, repo=repo))
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, ValueError):
        payload = {}
    return status, payload if isinstance(payload, dict) else {}


def _get(repo: str, path: str, token: str, *, request, timeout) -> tuple[bytes, str] | None:
    """远端那份的 (内容, sha)；不存在返回 None。"""
    status, payload = _call("GET", repo, path, token, None, request=request, timeout=timeout)
    if status == 404:
        return None
    if status != 200:
        raise ConfigBackupError(t("config_backup.http_error", code=status))
    try:
        content = base64.b64decode(str(payload.get("content") or ""))
    except ValueError as exc:
        raise ConfigBackupError(t("config_backup.not_a_config", repo=repo, path=path)) from exc
    return content, str(payload.get("sha") or "")


def _as_config(data: bytes) -> dict | None:
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def backup(config_path, repo: str, path: str, token: str, *, request: Request | None = None,
           now: float | None = None) -> BackupState:
    """把盘上的配置备份到 ``repo`` 的 ``path``。失败把原因记进状态文件后抛 ``ConfigBackupError``。"""
    config_path = Path(config_path)
    config_dir = config_path.parent
    now = time.time() if now is None else now
    path = clean_path(path)
    state = load_state(config_dir)
    try:
        try:
            data = config_path.read_bytes()
        except OSError as exc:
            raise ConfigBackupError(t("config_backup.local_unreadable", error=exc)) from exc
        if _as_config(data) is None:
            raise ConfigBackupError(t("config_backup.local_corrupt"))
        remote = _get(repo, path, token, request=request, timeout=REQUEST_TIMEOUT_S)
        if remote is None or remote[0] != data:
            body = {
                "message": f"big-fat-fish: back up config {datetime.fromtimestamp(now):%Y-%m-%d %H:%M}",
                "content": base64.b64encode(data).decode("ascii"),
            }
            if remote is not None:
                body["sha"] = remote[1]
            status, _payload = _call("PUT", repo, path, token, body, request=request, timeout=REQUEST_TIMEOUT_S)
            if status == 404:
                raise ConfigBackupError(t("config_backup.repo_not_found", repo=repo))
            if status not in (200, 201):
                raise ConfigBackupError(t("config_backup.http_error", code=status))
    except ConfigBackupError as exc:
        state.attempted_at, state.error = now, str(exc)
        _save_state(config_dir, state)
        raise
    state = BackupState(repo=repo, path=path, backed_up_at=now, fingerprint=fingerprint(data), attempted_at=now)
    _save_state(config_dir, state)
    return state


def fetch(repo: str, path: str, token: str, *, request: Request | None = None,
          timeout: float = REQUEST_TIMEOUT_S) -> bytes:
    """拉回备份内容；不存在或不是配置对象都抛 ``ConfigBackupError``。"""
    path = clean_path(path)
    remote = _get(repo, path, token, request=request, timeout=timeout)
    if remote is None:
        raise ConfigBackupError(t("config_backup.no_backup", repo=repo, path=path))
    if _as_config(remote[0]) is None:
        raise ConfigBackupError(t("config_backup.not_a_config", repo=repo, path=path))
    return remote[0]


def restore(config_path, repo: str, path: str, token: str, *, request: Request | None = None) -> Path | None:
    """用 GitHub 上的备份替换盘上的配置。返回替换前那份的留底路径（原来没有文件就是 None）。"""
    from .config import _write_durably

    config_path = Path(config_path)
    data = fetch(repo, path, token, request=request)
    kept = None
    if config_path.is_file():
        kept = config_path.with_name(f"{config_path.name}.before-restore")
        try:
            _write_durably(kept, config_path.read_bytes())
        except OSError as exc:
            raise ConfigBackupError(t("config_backup.local_unreadable", error=exc)) from exc
    try:
        _write_durably(config_path, data)
    except OSError as exc:
        raise ConfigBackupError(t("config_backup.write_failed", error=exc)) from exc
    state = load_state(config_path.parent)
    state.repo, state.path, state.rebuilt_at = repo, clean_path(path), 0.0
    state.fingerprint = fingerprint(data)
    _save_state(config_path.parent, state)
    return kept


def recover_at_startup(config_dir, *, request: Request | None = None) -> tuple[bytes, str] | None:
    """启动兜底：按状态文件记的仓库 / 路径拉一次备份。返回 (内容, 来源说明)；没配过或拉不到返回 None。"""
    state = load_state(config_dir)
    if not state.repo:
        return None
    token = stored_token()
    if not token:
        log.warning("配置损坏且没有可用的 .bak；钥匙串里没有 GitHub Token，无法从备份恢复")
        return None
    try:
        data = fetch(state.repo, state.path or DEFAULT_PATH, token, request=request or _default_request,
                     timeout=STARTUP_FETCH_TIMEOUT_S)
    except ConfigBackupError as exc:
        log.warning("配置损坏且没有可用的 .bak；从 GitHub 备份恢复失败: %s", exc)
        return None
    return data, f"GitHub {state.repo}:{state.path or DEFAULT_PATH}"
