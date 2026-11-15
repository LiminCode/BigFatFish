"""Back up config.json to a private GitHub repo and restore it (2026-11-14).

On 2026-11-13 a blue screen zeroed config.json; the pet rebuilt it from
defaults and every setting was lost. PR #40 added a local ``config.json.bak``;
this is the off-machine layer: the whole file goes to a GitHub repo the user
picks (their own private repo; never this public one), restore pulls it back,
and startup falls back to it when both config.json and .bak are bad.

GitHub is faked at the HTTP seam (``request(method, url, headers, body,
timeout) -> (status, body)``); repos and paths here are fictional.
"""

from __future__ import annotations

import base64
import json

import pytest

from pet import config_backup as cb
from pet.config import Config

REPO = "acme/handbook"


class FakeGitHub:
    """The Contents API subset the feature uses: GET and PUT one file."""

    def __init__(self, files: dict[str, bytes] | None = None, *, fail: int | None = None):
        self.files = dict(files or {})
        self.calls: list[tuple[str, str]] = []
        self.puts: list[dict] = []
        self.fail = fail

    def _sha(self, path: str) -> str:
        return f"sha-{len(self.files[path])}"

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url))
        assert headers.get("Authorization") == "Bearer tok"
        if self.fail:
            return self.fail, b'{"message": "nope"}'
        prefix = f"https://api.github.com/repos/{REPO}/contents/"
        assert url.startswith(prefix), url
        path = url[len(prefix):]
        if method == "GET":
            if path not in self.files:
                return 404, b'{"message": "Not Found"}'
            content = base64.b64encode(self.files[path]).decode()
            return 200, json.dumps({"sha": self._sha(path), "encoding": "base64", "content": content}).encode()
        if method == "PUT":
            payload = json.loads(body)
            if path in self.files:
                assert payload.get("sha") == self._sha(path), "updating needs the current sha"
            else:
                assert "sha" not in payload
            self.puts.append(payload)
            self.files[path] = base64.b64decode(payload["content"])
            return (200 if "sha" in payload else 201), b"{}"
        raise AssertionError(method)


def _saved(tmp_path, **changes) -> Config:
    cfg = Config(base=tmp_path)
    for key, value in changes.items():
        cfg.set(key, value)
    assert cfg.save()
    return cfg


def _zero_out(path) -> None:
    path.write_bytes(b"\x00" * path.stat().st_size)


# ---------------------------------------------------------------- settings


def test_settings_default_to_off_with_a_hidden_path():
    assert cb.normalize(None) == {"auto": False, "repo": "", "path": cb.DEFAULT_PATH}
    # A dot folder: Obsidian hides it and the pet's own knowledge-base sync skips it.
    assert cb.DEFAULT_PATH.startswith(".")


def test_settings_clean_repo_and_path():
    got = cb.normalize({"auto": "yes", "repo": "https://github.com/acme/handbook.git", "path": "\\pets\\cfg.json/"})
    assert got == {"auto": True, "repo": REPO, "path": "pets/cfg.json"}
    assert cb.normalize({"path": "../escape.json"})["path"] == cb.DEFAULT_PATH
    assert cb.normalize({"auto": "false"})["auto"] is False


def test_repo_falls_back_to_the_knowledge_base_repo():
    assert cb.target_repo(cb.normalize(None), "acme/notes") == "acme/notes"
    assert cb.target_repo(cb.normalize({"repo": REPO}), "acme/notes") == REPO
    assert cb.target_repo(cb.normalize(None), "") == ""


def test_config_round_trips_the_backup_settings(tmp_path):
    cfg = _saved(tmp_path, config_backup={"auto": True, "repo": REPO, "path": "x/config.json"})
    assert Config(base=tmp_path).get("config_backup") == {"auto": True, "repo": REPO, "path": "x/config.json"}
    cfg.set("config_backup", {"auto": 1, "path": ""})
    assert cfg.get("config_backup") == {"auto": True, "repo": "", "path": cb.DEFAULT_PATH}


# ---------------------------------------------------------------- back up


def test_backup_uploads_the_file_on_disk_and_records_it(tmp_path):
    cfg = _saved(tmp_path, on_top=False)
    hub = FakeGitHub()
    state = cb.backup(cfg.path, REPO, "pets/config.json", "tok", request=hub, now=1000.0)
    assert hub.files["pets/config.json"] == cfg.path.read_bytes()
    assert hub.puts[0]["message"].startswith("big-fat-fish: back up config")
    assert state.backed_up_at == 1000.0 and state.error == ""
    assert cb.load_state(cfg.dir).repo == REPO
    assert cb.load_state(cfg.dir).path == "pets/config.json"


def test_backup_updates_an_existing_file_with_its_sha(tmp_path):
    cfg = _saved(tmp_path)
    hub = FakeGitHub({"pets/config.json": b'{"old": true}'})
    cb.backup(cfg.path, REPO, "pets/config.json", "tok", request=hub, now=1.0)
    assert hub.files["pets/config.json"] == cfg.path.read_bytes()


def test_backup_skips_the_upload_when_github_already_has_it(tmp_path):
    cfg = _saved(tmp_path)
    hub = FakeGitHub({"pets/config.json": cfg.path.read_bytes()})
    state = cb.backup(cfg.path, REPO, "pets/config.json", "tok", request=hub, now=5.0)
    assert hub.puts == []
    assert state.backed_up_at == 5.0


def test_backup_never_uploads_a_corrupt_file(tmp_path):
    cfg = _saved(tmp_path)
    _zero_out(cfg.path)
    hub = FakeGitHub({"pets/config.json": b'{"good": true}'})
    with pytest.raises(cb.ConfigBackupError):
        cb.backup(cfg.path, REPO, "pets/config.json", "tok", request=hub, now=1.0)
    assert hub.files["pets/config.json"] == b'{"good": true}'
    assert hub.puts == []
    assert cb.load_state(cfg.dir).error


def test_backup_reports_a_denied_token(tmp_path):
    cfg = _saved(tmp_path)
    with pytest.raises(cb.ConfigBackupError, match="403"):
        cb.backup(cfg.path, REPO, "pets/config.json", "tok", request=FakeGitHub(fail=403), now=1.0)


# ---------------------------------------------------------------- restore


def test_restore_writes_the_backup_and_keeps_the_current_file(tmp_path):
    cfg = _saved(tmp_path, on_top=True)
    before = cfg.path.read_bytes()
    remote = dict(cfg.data, on_top=False)
    hub = FakeGitHub({"pets/config.json": json.dumps(remote).encode()})
    kept = cb.restore(cfg.path, REPO, "pets/config.json", "tok", request=hub)
    assert kept is not None and kept.read_bytes() == before
    assert Config(base=tmp_path).get("on_top") is False


def test_restore_refuses_a_backup_that_is_not_a_config(tmp_path):
    cfg = _saved(tmp_path)
    before = cfg.path.read_bytes()
    hub = FakeGitHub({"pets/config.json": b"\x00\x00\x00"})
    with pytest.raises(cb.ConfigBackupError):
        cb.restore(cfg.path, REPO, "pets/config.json", "tok", request=hub)
    assert cfg.path.read_bytes() == before


def test_restore_reports_a_missing_backup(tmp_path):
    cfg = _saved(tmp_path)
    with pytest.raises(cb.ConfigBackupError, match="pets/config.json"):
        cb.restore(cfg.path, REPO, "pets/config.json", "tok", request=FakeGitHub())


# ---------------------------------------------------------------- when to back up automatically


def test_needs_backup_once_a_day_and_only_when_settings_changed(tmp_path):
    cfg = _saved(tmp_path)
    assert cb.needs_backup(cfg.dir, cfg.path, now=0.0), "never backed up"
    cb.backup(cfg.path, REPO, cb.DEFAULT_PATH, "tok", request=FakeGitHub(), now=0.0)
    cfg.set("on_top", not cfg.get("on_top"))
    assert cfg.save()
    assert not cb.needs_backup(cfg.dir, cfg.path, now=3600.0), "less than a day since the last one"
    assert cb.needs_backup(cfg.dir, cfg.path, now=cb.BACKUP_INTERVAL_S + 1)


def test_moving_the_pet_alone_does_not_count_as_a_change(tmp_path):
    cfg = _saved(tmp_path)
    cb.backup(cfg.path, REPO, cb.DEFAULT_PATH, "tok", request=FakeGitHub(), now=0.0)
    cfg.set("rx", 0.25)
    cfg.set("ry", 0.75)
    assert cfg.save()
    assert not cb.needs_backup(cfg.dir, cfg.path, now=cb.BACKUP_INTERVAL_S * 3)


def test_a_failed_backup_retries_after_a_short_wait(tmp_path):
    cfg = _saved(tmp_path)
    with pytest.raises(cb.ConfigBackupError):
        cb.backup(cfg.path, REPO, cb.DEFAULT_PATH, "tok", request=FakeGitHub(fail=500), now=0.0)
    assert not cb.needs_backup(cfg.dir, cfg.path, now=60.0)
    assert cb.needs_backup(cfg.dir, cfg.path, now=cb.RETRY_AFTER_FAILURE_S + 1)


# ---------------------------------------------------------------- startup fallback


def _backed_up_then_zeroed(tmp_path, hub) -> Config:
    """A config that was backed up, then zeroed by a crash with no usable .bak."""
    cfg = _saved(tmp_path, on_top=False)
    cb.backup(cfg.path, REPO, cb.DEFAULT_PATH, "tok", request=hub, now=0.0)
    _zero_out(cfg.path)
    cfg.path.with_name(cfg.path.name + ".bak").unlink(missing_ok=True)
    return cfg


def test_startup_recovers_from_github_when_config_and_bak_are_both_bad(tmp_path, monkeypatch):
    hub = FakeGitHub()
    cfg = _backed_up_then_zeroed(tmp_path, hub)
    monkeypatch.setattr(cb, "_default_request", hub)
    monkeypatch.setattr(cb, "stored_token", lambda: "tok")
    again = Config(base=tmp_path)
    assert again.get("on_top") is False
    assert "GitHub" in str(again.recovered_from) and REPO in str(again.recovered_from)
    assert json.loads(cfg.path.read_text(encoding="utf-8"))["on_top"] is False, "written back to disk"
    assert hub.calls[-1][0] == "GET"
    assert hub.calls[-1][1].endswith(cb.DEFAULT_PATH)


def test_startup_uses_a_short_timeout_for_the_github_fallback(tmp_path, monkeypatch):
    hub = FakeGitHub()
    _backed_up_then_zeroed(tmp_path, hub)
    seen = []
    monkeypatch.setattr(cb, "_default_request", lambda *a: seen.append(a[4]) or hub(*a))
    monkeypatch.setattr(cb, "stored_token", lambda: "tok")
    Config(base=tmp_path)
    assert seen and max(seen) <= cb.STARTUP_FETCH_TIMEOUT_S


def test_rebuilt_from_defaults_pauses_automatic_backup(tmp_path, monkeypatch):
    """GitHub unreachable at startup: start on defaults, and never let the daily
    backup push those defaults over the good copy."""
    _backed_up_then_zeroed(tmp_path, FakeGitHub())
    monkeypatch.setattr(cb, "_default_request", FakeGitHub(fail=503))
    monkeypatch.setattr(cb, "stored_token", lambda: "tok")
    again = Config(base=tmp_path)
    assert again.get("on_top") is True, "defaults"
    assert cb.load_state(again.dir).rebuilt_at
    assert again.save()
    assert not cb.needs_backup(again.dir, again.path, now=cb.BACKUP_INTERVAL_S * 10)
    # A manual backup is the user saying "this is my config now": it lifts the pause.
    cb.backup(again.path, REPO, cb.DEFAULT_PATH, "tok", request=FakeGitHub(), now=1.0)
    assert not cb.load_state(again.dir).rebuilt_at


def test_restore_lifts_the_pause_too(tmp_path, monkeypatch):
    hub = FakeGitHub()
    _backed_up_then_zeroed(tmp_path, hub)
    monkeypatch.setattr(cb, "_default_request", FakeGitHub(fail=503))
    monkeypatch.setattr(cb, "stored_token", lambda: "tok")
    again = Config(base=tmp_path)
    cb.restore(again.path, REPO, cb.DEFAULT_PATH, "tok", request=hub)
    assert not cb.load_state(again.dir).rebuilt_at


def test_no_backup_configured_means_no_network_at_startup(tmp_path, monkeypatch):
    cfg = _saved(tmp_path)
    _zero_out(cfg.path)
    monkeypatch.setattr(cb, "_default_request", lambda *a: pytest.fail("no backup was ever made"))
    monkeypatch.setattr(cb, "stored_token", lambda: pytest.fail("no backup was ever made"))
    again = Config(base=tmp_path)
    assert again.recovered_from is None
    assert not cb.load_state(again.dir).rebuilt_at, "nothing to protect"


def test_a_runtime_reload_never_blocks_on_github(tmp_path, monkeypatch):
    hub = FakeGitHub()
    _backed_up_then_zeroed(tmp_path, hub)
    monkeypatch.setattr(cb, "_default_request", FakeGitHub(fail=503))
    monkeypatch.setattr(cb, "stored_token", lambda: "tok")
    cfg = Config(base=tmp_path)
    _zero_out(cfg.path)
    monkeypatch.setattr(cb, "_default_request", lambda *a: pytest.fail("reload on the GUI thread"))
    cfg.reload()


def test_a_bak_still_wins_over_github(tmp_path, monkeypatch):
    cfg = _saved(tmp_path, on_top=False)
    cb.backup(cfg.path, REPO, cb.DEFAULT_PATH, "tok", request=FakeGitHub(), now=0.0)
    assert cfg.save()                                  # leaves a good .bak
    _zero_out(cfg.path)
    monkeypatch.setattr(cb, "_default_request", lambda *a: pytest.fail(".bak was usable"))
    again = Config(base=tmp_path)
    assert again.get("on_top") is False
    assert str(again.recovered_from).endswith(".bak")
