# -*- coding: utf-8 -*-
"""本地知识库：GitHub 仓库 → 本地副本 → 对话时用客户端工具读本地。

边界用替身：GitHub 的下载是一个返回 zip 字节的函数，Claude 客户端按脚本吐流，
钥匙串是内存字典。真实链路见 PR 报告的实机记录。
"""

from __future__ import annotations

import io
import threading
import urllib.error
import zipfile
from types import SimpleNamespace

import pytest

from pet.chat import anthropic_provider as ap
from pet.chat import knowledge_base as kb
from pet.chat.models import ChatSettings, ProviderConfig
from pet.chat.providers import ProviderError

REPO = "acme/handbook"
DAY = 24 * 3600


def _zip(files: dict[str, str | bytes], top: str = "acme-handbook-110cb8a") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, content in files.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            bundle.writestr(f"{top}/{name}", data)
    return buffer.getvalue()


VAULT = {
    "INDEX.md": "# Handbook\n地图：项目在 projects/。\n",
    "projects/garden/notes.md": "番茄用 K-12 营养土。\n每周浇两次水。\n",
    "profile/About me.md": "示例用户，喜欢种菜。\n",
    "profile/photo.png": b"\x89PNG....",
    ".obsidian/workspace.json": "{}",
    ".gitignore": "*.tmp\n",
}


def _fetch(archive: bytes, calls: list | None = None):
    def fetch(url, headers):
        if calls is not None:
            calls.append((url, dict(headers)))
        return archive
    return fetch


@pytest.fixture
def synced(tmp_path):
    kb.sync(tmp_path, REPO, fetch=_fetch(_zip(VAULT)), now=1_000_000.0)
    return tmp_path


# ---------------------------------------------------------------- 仓库名

@pytest.mark.parametrize("text, repo", [
    ("acme/handbook", REPO),
    ("  https://github.com/acme/handbook  ", REPO),
    ("https://github.com/acme/handbook.git", REPO),
    ("github.com/acme/handbook/tree/main/User", REPO),
    ("git@github.com:acme/handbook.git", REPO),
    ("handbook", ""),
    ("https://gitlab.com/a/b", ""),
    ("../../etc/passwd", ""),
    ("", ""),
])
def test_repo_is_read_from_the_forms_people_actually_paste(text, repo):
    assert kb.parse_repo(text) == repo


# ---------------------------------------------------------------- 同步

def test_sync_keeps_text_files_only_and_records_the_state(tmp_path):
    calls: list = []

    state = kb.sync(tmp_path, f"https://github.com/{REPO}", "  ghp_secret ", fetch=_fetch(_zip(VAULT), calls),
                    now=1_000_000.0)

    root = kb.content_dir(tmp_path)
    kept = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert kept == ["INDEX.md", "profile/About me.md", "projects/garden/notes.md"], \
        "图片、点开头的目录和文件不进副本；GitHub 加的顶层目录要去掉"
    assert (state.repo, state.files, state.synced_at, state.error) == (REPO, 3, 1_000_000.0, "")
    assert kb.load_state(tmp_path) == state and kb.has_copy(tmp_path, REPO)
    url, headers = calls[0]
    assert url == "https://api.github.com/repos/acme/handbook/zipball"
    assert headers["Authorization"] == "Bearer ghp_secret"
    assert "ghp_secret" not in (kb.base_dir(tmp_path) / "state.json").read_text(encoding="utf-8")


def test_public_repos_sync_without_a_token(tmp_path):
    calls: list = []
    kb.sync(tmp_path, REPO, fetch=_fetch(_zip(VAULT), calls))
    assert "Authorization" not in calls[0][1]


def test_archive_entries_cannot_escape_the_copy(tmp_path):
    hostile = _zip({"ok.md": "fine", "../../evil.md": "x", "a/../../evil2.md": "x", "C:/evil3.md": "x"})

    kb.sync(tmp_path, REPO, fetch=_fetch(hostile))

    assert [p.name for p in tmp_path.rglob("*.md")] == ["ok.md"]
    assert not list(tmp_path.parent.glob("evil*"))


def test_a_new_sync_replaces_the_whole_copy(synced):
    kb.sync(synced, REPO, fetch=_fetch(_zip({"INDEX.md": "新版地图", "new.md": "新增"})), now=1_000_500.0)

    root = kb.content_dir(synced)
    assert (root / "INDEX.md").read_text(encoding="utf-8") == "新版地图"
    assert not (root / "profile").exists(), "仓库里删掉的文件，副本里也不该留着"
    assert sorted(p.name for p in kb.base_dir(synced).iterdir()) == ["current", "state.json"], "不留临时目录"


@pytest.mark.parametrize("failure, needle", [
    (urllib.error.HTTPError("u", 404, "Not Found", None, None), "找不到仓库"),
    (urllib.error.HTTPError("u", 401, "Unauthorized", None, None), "Token"),
    (urllib.error.URLError("timed out"), "网络错误"),
    (b"not a zip", "zip"),
    (_zip({"logo.png": b"png"}), "没有可读的文本文件"),
])
def test_a_failed_sync_keeps_the_old_copy_and_says_why(synced, failure, needle):
    def fetch(_url, _headers):
        if isinstance(failure, Exception):
            raise failure
        return failure

    with pytest.raises(kb.KnowledgeBaseError, match=needle):
        kb.sync(synced, REPO, fetch=fetch, now=1_000_900.0)

    state = kb.load_state(synced)
    assert needle in state.error and state.attempted_at == 1_000_900.0
    assert state.synced_at == 1_000_000.0 and kb.has_copy(synced, REPO)
    assert (kb.content_dir(synced) / "INDEX.md").exists()
    assert kb.describe(synced, REPO).startswith("同步失败")


def test_private_repo_without_a_token_is_told_where_to_put_one(tmp_path):
    def fetch(_url, _headers):
        raise urllib.error.HTTPError("u", 404, "Not Found", None, None)

    with pytest.raises(kb.KnowledgeBaseError, match="连接器.*Token"):
        kb.sync(tmp_path, REPO, fetch=fetch)


def test_sync_is_due_daily_on_repo_change_and_backs_off_after_a_failure(synced):
    t0 = 1_000_000.0
    assert kb.needs_sync(synced, REPO, now=t0 + 3600) is False
    assert kb.needs_sync(synced, REPO, now=t0 + DAY) is True
    assert kb.needs_sync(synced, "someone/else", now=t0 + 60) is True, "换了仓库：现有副本不算数"
    assert kb.needs_sync(synced, "", now=t0 + 10 * DAY) is False

    def fetch(_url, _headers):
        raise urllib.error.URLError("offline")

    with pytest.raises(kb.KnowledgeBaseError):
        kb.sync(synced, REPO, fetch=fetch, now=t0 + DAY)
    assert kb.needs_sync(synced, REPO, now=t0 + DAY + 600) is False, "刚失败过：不每个检查周期都打一次 GitHub"
    assert kb.needs_sync(synced, REPO, now=t0 + DAY + kb.RETRY_AFTER_FAILURE_S) is True


# ---------------------------------------------------------------- 读本地副本

def test_notes_can_be_listed_read_and_searched(synced):
    base = kb.KnowledgeBase(kb.content_dir(synced))

    assert base.list("").splitlines()[:2] == ["profile/", "projects/"]
    assert "INDEX.md" in base.list("")
    assert base.read("projects/garden/notes.md").startswith("番茄")
    assert base.read("profile\\About me.md").startswith("示例用户")
    assert base.search("k-12") == "projects/garden/notes.md:1: 番茄用 K-12 营养土。"
    assert "profile/About me.md  （文件名匹配）" in base.search("about me")
    assert base.search("不存在的词") == "没有找到「不存在的词」"


@pytest.mark.parametrize("path", ["../state.json", "..", "projects/../../state.json", "C:/Windows/win.ini"])
def test_reads_stay_inside_the_copy(synced, path):
    base = kb.KnowledgeBase(kb.content_dir(synced))
    with pytest.raises(kb.KnowledgeBaseError):
        base.read(path)
    with pytest.raises(kb.KnowledgeBaseError):
        base.list(path)


def test_long_notes_are_cut_with_a_notice(tmp_path):
    kb.sync(tmp_path, REPO, fetch=_fetch(_zip({"big.md": "长" * 50_000})))
    text = kb.KnowledgeBase(kb.content_dir(tmp_path)).read("big.md")
    assert len(text) < 41_000 and "共 50000 字" in text


# ---------------------------------------------------------------- 什么时候带工具

def _claude(**overrides) -> ProviderConfig:
    cfg = ProviderConfig("claude", name="Claude", base_url="https://api.anthropic.com",
                         model="claude-sonnet-5", api_key="sk-ant-test")
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _settings(**overrides) -> ChatSettings:
    settings = ChatSettings.defaults()
    settings.providers = {"claude": _claude()}
    settings.active_provider = "claude"
    settings.knowledge_base_enabled, settings.knowledge_base_repo = True, REPO
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def test_tools_are_offered_only_with_a_synced_copy_on_the_claude_channel(synced, tmp_path_factory):
    tools = kb.toolset_for(_settings(), _claude(), synced)
    assert [d["name"] for d in tools.definitions] == ["kb_read", "kb_list", "kb_search"]
    assert REPO in tools.system_note and "INDEX.md" in tools.system_note
    assert tools.run("kb_read", {"path": "INDEX.md"}).startswith("# Handbook")

    assert kb.toolset_for(_settings(knowledge_base_enabled=False), _claude(), synced) is None, "默认关"
    assert kb.toolset_for(_settings(knowledge_base_repo="someone/else"), _claude(), synced) is None, "副本是别的仓库的"
    assert kb.toolset_for(_settings(), ProviderConfig("ds"), synced) is None, "OpenAI 兼容通道暂不支持"
    assert kb.toolset_for(_settings(), _claude(), tmp_path_factory.mktemp("empty")) is None, "还没同步过"
    gateway = _claude(base_url="https://gateway.corp.example/claude", api_format="anthropic")
    assert kb.toolset_for(_settings(), gateway, synced) is not None, "工具在本地执行，经网关访问 Claude 也能用"


def test_settings_round_trip_and_default_off():
    assert (ChatSettings.defaults().knowledge_base_enabled, ChatSettings.defaults().knowledge_base_repo) == (False, "")
    saved = _settings()
    saved.active_config.client_tools = object()
    data = saved.to_dict()
    restored = ChatSettings.from_dict(data)
    assert (restored.knowledge_base_enabled, restored.knowledge_base_repo) == (True, REPO)
    assert "client_tools" not in data["providers"]["claude"], "运行期挂上的工具不属于持久配置"


# ---------------------------------------------------------------- Claude 通道的工具循环

class _Stream:
    def __init__(self, text="", tool_calls=(), stop_reason=None):
        self._text = text
        content = [SimpleNamespace(type="text", text=text)] if text else []
        content += [SimpleNamespace(type="tool_use", id=i, name=n, input=a) for i, n, a in tool_calls]
        self.final = SimpleNamespace(stop_reason=stop_reason or ("tool_use" if tool_calls else "end_turn"),
                                     stop_details=None, content=content)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    @property
    def text_stream(self):
        if self._text:
            yield self._text

    def get_final_message(self):
        return self.final

    def close(self):
        pass


class _Client:
    def __init__(self, *streams):
        self._streams = list(streams)
        self.calls: list[tuple[str, dict]] = []
        self.messages = SimpleNamespace(stream=lambda **kw: self._open("messages", kw))
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: self._open("beta", kw)))

    def _open(self, surface, kwargs):
        self.calls.append((surface, kwargs))
        return self._streams.pop(0)


def _use(monkeypatch, *streams) -> _Client:
    client = _Client(*streams)
    monkeypatch.setattr(ap, "_sdk", lambda: SimpleNamespace(APIStatusError=(), APIConnectionError=(),
                        AuthenticationError=(), PermissionDeniedError=(), NotFoundError=(), RateLimitError=()))
    monkeypatch.setattr(ap, "_client", lambda *a, **k: client)
    return client


def _run(config, cancel=None) -> list[str]:
    messages = [{"role": "system", "content": "你是鲸鱼娘。"}, {"role": "user", "content": "我在种什么？"}]
    return list(ap.AnthropicProvider().stream(messages, config, cancel or threading.Event()))


def test_tool_calls_are_run_locally_and_fed_back_until_the_answer(monkeypatch, synced):
    tools = kb.toolset_for(_settings(), _claude(), synced)
    asking = _Stream("我查一下。", [("tu_1", "kb_read", {"path": "INDEX.md"}),
                                    ("tu_2", "kb_search", {"query": "K-12"})])
    client = _use(monkeypatch, asking, _Stream("你在种番茄。"))

    assert _run(_claude(client_tools=tools)) == ["我查一下。", "你在种番茄。"]

    (surface, first), (_surface, second) = client.calls
    assert surface == "messages", "客户端工具不需要 beta 入口"
    assert first["tools"] == kb.TOOL_DEFINITIONS and first["cache_control"] == {"type": "ephemeral"}
    assert first["system"] == f"你是鲸鱼娘。\n\n{tools.system_note}", "用法说明跟着工具走"
    assert second["messages"][:-2] == first["messages"]
    assert second["messages"][-2] == {"role": "assistant", "content": asking.final.content}
    results = second["messages"][-1]
    assert results["role"] == "user" and [r["tool_use_id"] for r in results["content"]] == ["tu_1", "tu_2"], \
        "同一轮的多个工具结果必须放在同一条 user 消息里"
    assert results["content"][0]["content"].startswith("# Handbook") and "is_error" not in results["content"][0]
    assert "K-12" in results["content"][1]["content"]


def test_a_failing_tool_reports_the_error_to_the_model_instead_of_aborting(monkeypatch, synced):
    tools = kb.toolset_for(_settings(), _claude(), synced)
    client = _use(monkeypatch, _Stream("", [("tu_1", "kb_read", {"path": "../state.json"}),
                                            ("tu_2", "kb_delete", {})]), _Stream("读不到。"))

    assert _run(_claude(client_tools=tools)) == ["读不到。"]

    first, second = client.calls[1][1]["messages"][-1]["content"]
    assert first["is_error"] is True and "超出了知识库目录" in first["content"]
    assert second["is_error"] is True and "kb_delete" in second["content"]


def test_a_turn_that_never_stops_calling_tools_is_cut_off(monkeypatch, synced):
    tools = kb.toolset_for(_settings(), _claude(), synced)
    client = _use(monkeypatch, *(_Stream("", [(f"tu_{i}", "kb_list", {})]) for i in range(40)))

    with pytest.raises(ProviderError, match="没有说完"):
        _run(_claude(client_tools=tools))

    assert len(client.calls) <= 12


def test_cancelling_during_a_tool_round_stops_before_the_next_request(monkeypatch, synced):
    tools = kb.toolset_for(_settings(), _claude(), synced)
    cancel = threading.Event()
    real_run = tools.run
    tools.run = lambda name, args: (cancel.set(), real_run(name, args))[1]
    client = _use(monkeypatch, _Stream("", [("tu_1", "kb_list", {})]), _Stream("不该发出这一条"))

    assert _run(_claude(client_tools=tools), cancel) == []
    assert len(client.calls) == 1


def test_local_tools_and_the_github_connector_can_ride_together(monkeypatch, synced):
    tools = kb.toolset_for(_settings(), _claude(), synced)
    github = {"type": "url", "url": "https://api.githubcopilot.com/mcp/readonly", "name": "github",
              "authorization_token": "ghp_x"}
    client = _use(monkeypatch, _Stream("好"))

    _run(_claude(client_tools=tools, mcp_servers=[github]))

    surface, kwargs = client.calls[0]
    assert surface == "beta" and kwargs["betas"] == ["mcp-client-2025-11-20"]
    assert [t.get("name") or t["type"] for t in kwargs["tools"]] == ["mcp_toolset", "kb_read", "kb_list", "kb_search"]


def test_real_sdk_accepts_tools_and_top_level_caching_on_the_plain_stream():
    anthropic = pytest.importorskip("anthropic")
    import inspect

    params = inspect.signature(anthropic.Anthropic(api_key="x").messages.stream).parameters
    assert {"tools", "cache_control", "system", "messages"} <= set(params)


# ---------------------------------------------------------------- 配置与对话窗口接线

class _MemoryStore:
    shared: dict[str, str] = {}

    def __init__(self, *_a, **_k):
        pass

    def get(self, ref):
        return self.shared.get(ref, "") if ref else ""

    def set(self, ref, value):
        self.shared[ref] = value
        return True


@pytest.fixture
def store(monkeypatch):
    _MemoryStore.shared = {}
    monkeypatch.setattr("pet.chat.models.SecretStore", _MemoryStore)
    return _MemoryStore


def _kb_config(tmp_path, store, *, synced_copy=True):
    from pet.config import Config

    config = Config(base=tmp_path)
    settings = config.chat_settings()
    settings.providers = {"claude": _claude(api_key="")}
    settings.active_provider = "claude"
    settings.knowledge_base_enabled, settings.knowledge_base_repo = True, REPO
    config.set_chat_settings(settings)
    store.shared["provider/claude"] = "sk-ant-test"
    if synced_copy:
        kb.sync(config.dir, REPO, fetch=_fetch(_zip(VAULT)))
    return config


def test_config_resolves_the_toolset_from_saved_settings_and_the_local_copy(tmp_path, store):
    config = _kb_config(tmp_path, store)
    tools = config.resolve_client_tools(config.chat_settings().active_config)
    assert tools.run("kb_read", {"path": "profile/About me.md"}).startswith("示例用户")

    empty = _kb_config(tmp_path / "other", store, synced_copy=False)
    assert empty.resolve_client_tools(empty.chat_settings().active_config) is None


class _RecordingService:
    busy = False

    def __init__(self):
        self.sent: list = []

    def send(self, messages, config, request_id=None):
        self.sent.append((messages, config))
        return "rid-1"

    def stop(self):
        pass


@pytest.mark.parametrize("window_path", ["pet.chat.widgets:ChatWindow", "pet.chat.legacy_widgets:ChatWindow"])
def test_chat_windows_send_with_the_knowledge_tools_attached(tmp_path, store, window_path):
    import importlib

    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    module, name = window_path.split(":")
    window = getattr(importlib.import_module(module), name)(_kb_config(tmp_path, store), "shenshen")
    try:
        window.service = _RecordingService()
        window.input.setPlainText("我在种什么？")
        window.send_message()
        assert isinstance(window.service.sent[0][1].client_tools, kb.KnowledgeToolset)
    finally:
        window.close()


def test_quick_chat_sends_with_the_knowledge_tools_attached(tmp_path, store):
    from PySide6.QtWidgets import QApplication

    from pet.quick_chat import QuickChatBubble

    QApplication.instance() or QApplication([])
    bubble = QuickChatBubble(_kb_config(tmp_path, store))
    try:
        bubble.service = _RecordingService()
        bubble.input.setText("我在种什么？")
        bubble._send()
        assert isinstance(bubble.service.sent[0][1].client_tools, kb.KnowledgeToolset)
    finally:
        bubble.close()


# ---------------------------------------------------------------- 设置页

def _page(tmp_path):
    from PySide6.QtWidgets import QApplication

    from pet.chat.ai_settings_page import _AiSettingsPage
    from pet.config import Config

    QApplication.instance() or QApplication([])
    config = Config(base=tmp_path)
    return config, _AiSettingsPage(config)


def _pump(predicate, budget_s: float = 20.0) -> bool:
    import time

    from PySide6.QtWidgets import QApplication

    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        QApplication.instance().processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_settings_page_saves_the_switch_and_the_normalised_repo(tmp_path, store):
    from pet.config import Config
    from pet.settings_widgets import SettingRow

    config, page = _page(tmp_path)
    try:
        repo_row = page.findChild(SettingRow, "settingRow_knowledge_base_repo")
        sync_row = page.findChild(SettingRow, "settingRow_knowledge_base_sync")
        token_row = page.findChild(SettingRow, "settingRow_github_token")
        assert page.knowledge_base.isChecked() is False
        assert repo_row.isHidden() and sync_row.isHidden() and token_row.isHidden()
        page.knowledge_base.setChecked(True)
        assert not repo_row.isHidden() and not sync_row.isHidden()
        assert not token_row.isHidden(), "私有仓库的 Token 与连接器共用同一行，连接器关着也要能填"
        page.knowledge_base_repo.setText(f" https://github.com/{REPO}.git ")
        page.save()
        config.save()
    finally:
        page.deleteLater()

    saved = Config(base=tmp_path).chat_settings()
    assert (saved.knowledge_base_enabled, saved.knowledge_base_repo) == (True, REPO)


def test_sync_now_uses_the_form_values_and_reports_the_outcome(tmp_path, store):
    config, page = _page(tmp_path)
    calls: list = []
    try:
        page.knowledge_base.setChecked(True)
        page.knowledge_base_repo.setText(REPO)
        page.github_token.setText("ghp_typed")

        def fake_sync(config_dir, repo, token):
            calls.append((config_dir, repo, token))
            return kb.sync(config_dir, repo, token, fetch=_fetch(_zip(VAULT)))

        page._kb_sync = fake_sync
        page.knowledge_base_sync.click()
        assert _pump(lambda: page.knowledge_base_sync.isEnabled() and bool(calls))
        assert calls == [(config.dir, REPO, "ghp_typed")]
        assert "3 个文件" in page.knowledge_base_status.text()

        def failing_sync(_config_dir, _repo, _token):
            raise kb.KnowledgeBaseError("找不到仓库")

        page._kb_sync = failing_sync
        page.knowledge_base_sync.click()
        assert _pump(lambda: "找不到仓库" in page.knowledge_base_status.text())
        assert page.knowledge_base_sync.isEnabled()

        page.knowledge_base_repo.setText("不是仓库")
        page.knowledge_base_sync.click()
        assert "owner/repo" in page.knowledge_base_status.text()
    finally:
        page.deleteLater()


# ---------------------------------------------------------------- 每日同步

def _scheduler(config, sync_calls: list, *, now: float, outcome=None):
    from pet.chat.knowledge_sync import KnowledgeBaseSync

    def fake_sync(config_dir, repo, token):
        sync_calls.append((repo, token))
        if isinstance(outcome, Exception):
            raise outcome
        return kb.sync(config_dir, repo, token, fetch=_fetch(_zip(VAULT)), now=now)

    return KnowledgeBaseSync(config, sync=fake_sync, spawn=lambda run: run(), clock=lambda: now)


def test_daily_sync_runs_when_due_and_stays_quiet_otherwise(tmp_path, store):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    config = _kb_config(tmp_path, store, synced_copy=False)
    store.shared["connector/github"] = "ghp_live"
    calls: list = []

    first = _scheduler(config, calls, now=2_000_000.0)
    assert first.check() is True and calls == [(REPO, "ghp_live")], "还没有副本：立刻同步"
    assert _pump(lambda: not first.busy)
    assert kb.has_copy(config.dir, REPO)
    assert first.check() is False and len(calls) == 1, "副本是新的：不重复下载"

    next_day = _scheduler(config, calls, now=2_000_000.0 + DAY)
    assert next_day.check() is True and len(calls) == 2
    for scheduler in (first, next_day):
        scheduler.stop()


def test_daily_sync_does_nothing_when_the_feature_is_off(tmp_path, store):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    config = _kb_config(tmp_path, store, synced_copy=False)
    settings = config.chat_settings()
    settings.knowledge_base_enabled = False
    config.set_chat_settings(settings)
    calls: list = []

    scheduler = _scheduler(config, calls, now=2_000_000.0)
    assert scheduler.check() is False and calls == []
    scheduler.stop()


def test_a_failed_daily_sync_is_logged_and_retried_later_not_immediately(tmp_path, store):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    config = _kb_config(tmp_path, store, synced_copy=False)
    calls: list = []

    def offline(_url, _headers):
        raise urllib.error.URLError("offline")

    from pet.chat.knowledge_sync import KnowledgeBaseSync

    def failing(config_dir, repo, token):
        calls.append(repo)
        return kb.sync(config_dir, repo, token, fetch=offline, now=2_000_000.0)

    scheduler = KnowledgeBaseSync(config, sync=failing, spawn=lambda run: run(), clock=lambda: 2_000_000.0)
    assert scheduler.check() is True
    assert _pump(lambda: not scheduler.busy)
    assert scheduler.check() is False and calls == [REPO], "失败后在退避期内不重试"
    scheduler.stop()
