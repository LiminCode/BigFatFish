"""配置写盘扛得住系统崩溃（2026-11-13 实机事故：蓝屏后 config.json 变成全零，
桌宠按默认值重建，用户的设置全部丢失）。

- 保存：临时文件内容先刷到磁盘再替换，崩溃后盘上要么是旧配置、要么是新配置，
  不会出现「长度对、内容全零」的文件。
- 保存：替换前把盘上那份完好的配置留作 ``<name>.bak``（上一份完好配置）。
- 加载：配置损坏时先退回 ``.bak``，并把它写回原文件；没有 ``.bak`` 才用默认值。
"""

from __future__ import annotations

import json
import os

from pet.config import Config


def _cfg(tmp_path) -> Config:
    return Config(base=tmp_path)


def _zero_out(path) -> None:
    """模拟崩溃：文件长度落了盘、内容没有。"""
    size = path.stat().st_size
    path.write_bytes(b"\x00" * size)


def test_save_flushes_the_temp_file_to_disk_before_replacing(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    events: list[tuple] = []
    real_fsync, real_replace = os.fsync, os.replace

    def spy_fsync(fd):
        events.append(("fsync", os.fstat(fd).st_size))
        return real_fsync(fd)

    def spy_replace(src, dst):
        events.append(("replace", os.fspath(src), os.fspath(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", spy_fsync)
    monkeypatch.setattr(os, "replace", spy_replace)
    assert cfg.save()
    target = os.fspath(cfg.path)
    final = next(i for i, e in enumerate(events) if e[0] == "replace" and e[2] == target)
    flushed = [e for e in events[:final] if e[0] == "fsync"]
    assert flushed, f"替换 config.json 之前必须先把临时文件刷盘: {events}"
    assert flushed[-1][1] == cfg.path.stat().st_size, "刷盘的是即将换上去的那份内容"


def test_a_zeroed_config_recovers_from_the_last_good_copy(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.data["dynamic_island"]["style"] = "metro"
    assert cfg.save()
    assert cfg.save()                     # 第二次保存时，盘上那份完好配置留作 .bak
    backup = cfg.path.with_name(cfg.path.name + ".bak")
    assert json.loads(backup.read_text(encoding="utf-8"))["dynamic_island"]["style"] == "metro"

    _zero_out(cfg.path)
    again = _cfg(tmp_path)
    assert again.data["dynamic_island"]["style"] == "metro", "损坏时退回上一份完好配置，而不是默认值"
    assert list(tmp_path.rglob("config.json.corrupt-*")), "损坏的原文件照旧另存一份"
    restored = json.loads(again.path.read_text(encoding="utf-8"))
    assert restored["dynamic_island"]["style"] == "metro", "退回后立刻写回 config.json"


def test_saving_over_a_corrupt_file_keeps_the_good_backup(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.data["dynamic_island"]["style"] = "metro"
    assert cfg.save()
    assert cfg.save()
    backup = cfg.path.with_name(cfg.path.name + ".bak")
    _zero_out(cfg.path)
    cfg.reload()                          # 主进程的目录监视会这样重载一次，发现文件坏了
    cfg.data["dynamic_island"]["style"] = "glass"
    assert cfg.save()                     # 盘上是坏文件：不许拿它顶掉 .bak
    assert json.loads(backup.read_text(encoding="utf-8"))["dynamic_island"]["style"] == "metro"
    assert json.loads(cfg.path.read_text(encoding="utf-8"))["dynamic_island"]["style"] == "glass"


def test_the_backup_is_a_separate_file_from_the_new_config(tmp_path):
    """.bak 是替换前那一份；之后的保存改的是新文件，不会顺带改到 .bak。"""
    cfg = _cfg(tmp_path)
    cfg.data["dynamic_island"]["style"] = "metro"
    assert cfg.save()
    assert cfg.save()
    cfg.data["dynamic_island"]["style"] = "glass"
    assert cfg.save()
    backup = cfg.path.with_name(cfg.path.name + ".bak")
    assert json.loads(backup.read_text(encoding="utf-8"))["dynamic_island"]["style"] == "metro"
    assert json.loads(cfg.path.read_text(encoding="utf-8"))["dynamic_island"]["style"] == "glass"


def test_a_zeroed_config_without_a_backup_still_starts_from_defaults(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.data["dynamic_island"]["style"] = "metro"
    assert cfg.save()                     # 只保存过一次：还没有 .bak
    _zero_out(cfg.path)
    again = _cfg(tmp_path)
    assert again.data["dynamic_island"]["style"] != "metro"
    assert list(tmp_path.rglob("config.json.corrupt-*"))


def test_recovery_at_startup_is_logged_and_keeps_the_log_file_working(tmp_path):
    """真实子进程走启动顺序（Config → _setup_logging）：退回 .bak 这件事要写进 pet-<pid>.log，
    且日志初始化之前的告警不许抢先给根 logger 装上控制台 handler——否则 basicConfig 成了空操作，
    整个进程的日志都不进文件（2026-11-13 真机首轮就是这样：pet-<pid>.log 一直 0 字节）。"""
    import subprocess
    import sys
    from pathlib import Path

    cfg = _cfg(tmp_path)
    assert cfg.save()
    assert cfg.save()
    _zero_out(cfg.path)
    script = (
        "import logging, os, sys\n"
        "from pathlib import Path\n"
        "from pet.config import Config\n"
        "from pet.app import _setup_logging\n"
        "c = Config(base=Path(sys.argv[1]))\n"
        "_setup_logging(c)\n"
        "logging.info('after-setup')\n"
        "logging.shutdown()\n"
        "print(os.getpid())\n"
    )
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")
    repo = Path(__file__).resolve().parents[1]
    out = subprocess.run([sys.executable, "-c", script, str(tmp_path)], cwd=repo, env=env,
                         capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert out.returncode == 0, out.stderr
    pid = out.stdout.strip().splitlines()[-1]
    log = (cfg.dir / f"pet-{pid}.log").read_text(encoding="utf-8")
    assert "after-setup" in log, f"日志文件没装上: {log!r} / stderr={out.stderr!r}"
    assert "已退回上一份完好配置" in log
