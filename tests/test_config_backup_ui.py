"""Settings > General > Config backup, and the daily auto-backup timer (2026-11-14).

GitHub is faked at the HTTP seam via ``config_backup._default_request``; the
worker thread is run inline so results arrive on the GUI thread deterministically.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from pet import config_backup as cb
from pet import settings_config_backup as ui
from pet.config import Config
from pet.config_backup_sync import ConfigBackupSync

from tests.test_config_backup import REPO, FakeGitHub

app = QApplication.instance() or QApplication([])


def _dialog(config: Config, monkeypatch):
    from pet import modern_settings_dialog as settings_mod

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    return settings_mod.ModernSettingsDialog(config, include_ai=False)


def _row(dialog, key):
    from pet.settings_widgets import SettingRow

    row = dialog.findChild(SettingRow, f"settingRow_{key}")
    assert row is not None, key
    return row


def _close(widget):
    widget._saved_via_button = True
    widget.close()
    widget.deleteLater()
    app.processEvents()


def _inline(monkeypatch, hub):
    monkeypatch.setattr(ui, "_spawn", lambda target: target())
    monkeypatch.setattr(cb, "_default_request", hub)
    monkeypatch.setattr(cb, "stored_token", lambda: "tok")


# ---------------------------------------------------------------- the section


def test_general_page_has_the_backup_rows_with_defaults(tmp_path, monkeypatch):
    dialog = _dialog(Config(base=tmp_path), monkeypatch)
    try:
        for key in ("config_backup_auto", "config_backup_repo", "config_backup_path", "config_backup_actions"):
            _row(dialog, key)
        assert dialog.config_backup_auto.isChecked() is False
        assert dialog.config_backup_path.placeholderText() == cb.DEFAULT_PATH
        assert dialog.config_backup_repo.placeholderText() == "owner/repo"
        assert dialog.config_backup_status.text() == cb.describe(dialog.config.dir)
    finally:
        _close(dialog)


def test_repo_placeholder_is_the_knowledge_base_repo(tmp_path, monkeypatch):
    config = Config(base=tmp_path)
    chat = dict(config.get("chat"))
    chat["knowledge_base_repo"] = "acme/notes"
    config.set("chat", chat)
    dialog = _dialog(config, monkeypatch)
    try:
        assert dialog.config_backup_repo.placeholderText() == "acme/notes"
    finally:
        _close(dialog)


def test_saving_settings_persists_the_backup_settings(tmp_path, monkeypatch):
    dialog = _dialog(Config(base=tmp_path), monkeypatch)
    try:
        dialog.config_backup_auto.setChecked(True)
        dialog.config_backup_repo.setText(f"https://github.com/{REPO}")
        dialog.config_backup_path.setText("pets/config.json")
        assert dialog._write_config()
    finally:
        _close(dialog)
    assert Config(base=tmp_path).get("config_backup") == {"auto": True, "repo": REPO, "path": "pets/config.json"}


def test_back_up_now_saves_the_form_first_then_uploads_it(tmp_path, monkeypatch):
    hub = FakeGitHub()
    _inline(monkeypatch, hub)
    dialog = _dialog(Config(base=tmp_path), monkeypatch)
    try:
        dialog.config_backup_repo.setText(REPO)
        dialog.on_top_check.setChecked(not dialog.on_top_check.isChecked())
        wanted = dialog.on_top_check.isChecked()
        assert ui.run_backup(dialog)
        app.processEvents()
        uploaded = json.loads(hub.files[cb.DEFAULT_PATH])
        assert uploaded["on_top"] is wanted, "the upload carries what the form shows"
        assert uploaded["config_backup"]["repo"] == REPO
        assert "acme/handbook" in dialog.config_backup_status.text()
        assert dialog.config_backup_now.isEnabled()
    finally:
        _close(dialog)


def test_back_up_now_without_a_repo_says_so(tmp_path, monkeypatch):
    _inline(monkeypatch, lambda *a: (_ for _ in ()).throw(AssertionError("no request")))
    dialog = _dialog(Config(base=tmp_path), monkeypatch)
    try:
        assert not ui.run_backup(dialog)
        assert dialog.config_backup_status.text() == cb.t("config_backup.no_repo")
    finally:
        _close(dialog)


def test_a_failed_backup_shows_why_and_reenables_the_buttons(tmp_path, monkeypatch):
    _inline(monkeypatch, FakeGitHub(fail=403))
    dialog = _dialog(Config(base=tmp_path), monkeypatch)
    try:
        dialog.config_backup_repo.setText(REPO)
        ui.run_backup(dialog)
        app.processEvents()
        assert "403" in dialog.config_backup_status.text()
        assert dialog.config_backup_now.isEnabled() and dialog.config_backup_restore.isEnabled()
    finally:
        _close(dialog)


def test_restore_replaces_the_config_and_closes_without_saving_the_old_form(tmp_path, monkeypatch):
    config = Config(base=tmp_path)
    config.set("on_top", True)
    config.save()
    remote = dict(config.data, on_top=False)
    _inline(monkeypatch, FakeGitHub({cb.DEFAULT_PATH: json.dumps(remote).encode()}))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dialog = _dialog(config, monkeypatch)
    saved = []
    dialog.saved.connect(lambda: saved.append(True))
    dialog.show()
    dialog.config_backup_repo.setText(REPO)
    assert dialog.on_top_check.isChecked() is True
    assert ui.run_restore(dialog)
    app.processEvents()
    import shiboken6

    assert not shiboken6.isValid(dialog) or not dialog.isVisible(), "settings closes after a restore"
    assert saved, "the in-process host is told to apply the restored config"
    assert Config(base=tmp_path).get("on_top") is False, "closing must not write the stale form back"
    assert config.path.with_name("config.json.before-restore").is_file()
    if shiboken6.isValid(dialog):
        dialog.deleteLater()
        app.processEvents()


def test_cancelling_restore_changes_nothing(tmp_path, monkeypatch):
    _inline(monkeypatch, lambda *a: (_ for _ in ()).throw(AssertionError("no request")))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    dialog = _dialog(Config(base=tmp_path), monkeypatch)
    try:
        dialog.config_backup_repo.setText(REPO)
        assert not ui.run_restore(dialog)
        assert dialog.config_backup_restore.isEnabled()
    finally:
        _close(dialog)


# ---------------------------------------------------------------- the daily timer


def _sync(config, calls, *, token="tok", now=10_000.0):
    def backup(path, repo, repo_path, tok):
        calls.append((repo, repo_path, tok))

    return ConfigBackupSync(config, backup=backup, token=lambda: token, spawn=lambda f: f(), clock=lambda: now)


def test_timer_backs_up_when_auto_is_on_and_due(tmp_path):
    config = Config(base=tmp_path)
    config.set("config_backup", {"auto": True, "repo": REPO})
    config.save()
    calls = []
    assert _sync(config, calls).check()
    assert calls == [(REPO, cb.DEFAULT_PATH, "tok")]


def test_timer_does_nothing_while_auto_is_off(tmp_path):
    config = Config(base=tmp_path)
    config.set("config_backup", {"auto": False, "repo": REPO})
    config.save()
    calls = []
    assert not _sync(config, calls).check()
    assert calls == []


def test_timer_falls_back_to_the_knowledge_base_repo(tmp_path):
    config = Config(base=tmp_path)
    chat = dict(config.get("chat"))
    chat["knowledge_base_repo"] = "acme/notes"
    config.set("chat", chat)
    config.set("config_backup", {"auto": True})
    config.save()
    calls = []
    assert _sync(config, calls).check()
    assert calls[0][0] == "acme/notes"


def test_timer_needs_a_token(tmp_path):
    config = Config(base=tmp_path)
    config.set("config_backup", {"auto": True, "repo": REPO})
    config.save()
    calls = []
    assert not _sync(config, calls, token="").check()


def test_timer_stays_paused_after_a_rebuild_from_defaults(tmp_path):
    config = Config(base=tmp_path)
    config.set("config_backup", {"auto": True, "repo": REPO})
    config.save()
    cb.backup(config.path, REPO, cb.DEFAULT_PATH, "tok", request=FakeGitHub(), now=1.0)
    assert cb.mark_rebuilt(config.dir, now=2.0)
    calls = []
    assert not _sync(config, calls, now=cb.BACKUP_INTERVAL_S * 5).check()


def test_app_starts_the_timer_once(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from pet import config_backup_sync
    from pet.app import AppShell

    started = []
    monkeypatch.setattr(config_backup_sync.ConfigBackupSync, "start", lambda self: started.append(self))
    shell = SimpleNamespace(config=Config(base=tmp_path), app=app)
    AppShell._start_config_backup(shell)
    AppShell._start_config_backup(shell)
    assert len(started) == 1
    assert shell._config_backup_sync is started[0]
