# -*- coding: utf-8 -*-
"""笔记推送失败要说清原因（用户 2026-10-19：底部只见「git 没推上去:」）：

- 公司 git 钩子（Sphinx 理解检查）拦住推送时，说明要在终端里答问卷，并给「再推一次」按钮；
- 其余失败原样给 git 输出尾巴，没有输出也要说；状态行带完整 tooltip；
- 「再推一次」只在失败时可见，点了就再 sync 一次；中英文。
纪律：不起真的 wsl.exe、不碰真实数据目录。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import work_notes as wn
from pet.work_notes_ui import WorkNotesController
from tests.test_work_notes_ui import SLACK, _Fakes, _Host, _service, repo  # noqa: F401 - repo 是 fixture

app = QApplication.instance() or QApplication([])

SPHINX = ("Sphinx: understanding check needed for refs/heads/main (medium change). Sphinx: Git is waiting for your answers "
          "in the local Sphinx questionnaire. error: failed to push some refs to 'github.com:example/repo.git'")


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


def test_a_hook_blocked_push_is_explained_and_other_failures_show_the_tail():
    assert "Sphinx" in wn.describe_sync_failure(SPHINX) and "终端" in wn.describe_sync_failure(SPHINX)
    assert wn.describe_sync_failure("fatal: could not read from remote") == "git 没推上去：fatal: could not read from remote"
    assert wn.describe_sync_failure("") == "git 没推上去：（git 没有输出）"
    i18n.set_language("en")
    assert wn.describe_sync_failure(SPHINX).startswith("Not pushed: the company git hook")
    assert wn.describe_sync_failure("boom") == "git push failed: boom"


def test_the_panel_shows_the_reason_offers_push_again_and_pushes_everything(tmp_path, repo):  # noqa: F811
    class _HookBlocked(_Fakes):
        def sync(self, settings, message):
            self.syncs.append(message)
            return (False, SPHINX) if len(self.syncs) < 3 else (True, "")

    fakes = _HookBlocked()
    service = _service(tmp_path, repo, fakes)
    controller = WorkNotesController(_Host(), service)
    panel = controller.panel()
    try:
        assert panel.push_btn.isHidden(), "没失败时不显示「再推一次」"
        panel.input.setPlainText(f"{SLACK}\n看一下")
        panel.add_btn.click()
        status = panel.status_label.text()
        assert "Sphinx" in status and "终端" in status and "再推一次" in status
        assert panel.status_label.toolTip() == status and not panel.push_btn.isHidden()
        assert fakes.syncs == ["note: 记一条", "note: 总结"]
        panel.push_btn.click()
        assert fakes.syncs[-1] == "note: push" and panel.status_label.text() == "" and panel.push_btn.isHidden()
    finally:
        panel.deleteLater()
        app.processEvents()


def test_the_push_button_speaks_english(tmp_path, repo):  # noqa: F811
    service = _service(tmp_path, repo, _Fakes())
    service._config.set("ui_language", "en")
    panel = WorkNotesController(_Host(), service).panel()
    try:
        assert panel.push_btn.text() == "Push again" and "git hook" in panel.push_btn.toolTip()
    finally:
        panel.deleteLater()
        app.processEvents()
