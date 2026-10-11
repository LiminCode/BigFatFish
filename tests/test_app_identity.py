# -*- coding: utf-8 -*-
"""程序在系统里的身份：名字 BigFish 与鱼的图标。

实机现象：任务管理器里只有「Python」，任务栏上是 Python 的图标——从源码运行时进程
是 ``pythonw.exe``。两处来源不同：任务栏看窗口图标与应用用户模型 ID
（``pet/app_identity.py``），任务管理器看 exe 的版本资源（``tools/make_launcher.py``
生成改了名字和图标的 ``BigFish.exe``）。

纪律：offscreen；改 exe 资源的用例只在 Windows 上跑，改的是临时目录里的副本。
"""
from __future__ import annotations

import os
import struct
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import app_identity

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import make_launcher  # noqa: E402

app = QApplication.instance() or QApplication([])
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows 的 exe 资源 / 任务栏")


# ---------------------------------------------------------------- 任务栏：图标与分组
def test_app_icon_is_the_fish_icon_shipped_with_the_repo():
    path = app_identity.icon_path()
    assert path is not None and path.name == "icon.ico"
    assert not app_identity.app_icon().isNull()


def test_every_window_gets_the_app_icon():
    before = app.windowIcon()
    try:
        assert app_identity.apply_app_icon(app) is True
        assert not app.windowIcon().isNull()
    finally:
        app.setWindowIcon(before)


@windows_only
def test_process_declares_itself_as_bigfish_to_the_taskbar():
    import ctypes

    assert app_identity.set_process_identity() is True
    value = ctypes.c_wchar_p()
    assert ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID(ctypes.byref(value)) == 0
    try:
        assert value.value == app_identity.APP_USER_MODEL_ID == "BigFish.DesktopPet"
    finally:
        ctypes.windll.ole32.CoTaskMemFree(value)


def test_both_entry_points_set_the_identity_before_creating_windows():
    """主进程与设置页独立进程是两个入口：漏一个，那个窗口在任务栏上就还是 Python。"""
    for name in ("app.py", "__main__.py"):
        source = (REPO / "pet" / name).read_text(encoding="utf-8")
        declared = source.index("app_identity.set_process_identity()")
        created = source.index("QApplication(", declared)
        assert source.index("app_identity.apply_app_icon(app)", created) > created, name


# ---------------------------------------------------------------- 任务管理器：exe 的名字
def _strings(resource: bytes) -> str:
    return resource.decode("utf-16le", "ignore")


def test_version_resource_names_the_program_bigfish():
    resource = make_launcher.version_resource("BigFish", (3, 13, 15, 0), copyright_text="c")
    length, value_length, kind = struct.unpack_from("<HHH", resource, 0)
    assert length == len(resource) and value_length == 52 and kind == 0
    text = _strings(resource)
    for expected in ("VS_VERSION_INFO", "FileDescription\0\0BigFish", "ProductName\0\0BigFish",
                     "OriginalFilename\0BigFish.exe", "3.13.15.0", "Translation"):
        assert expected in text, expected
    fixed = resource.index(struct.pack("<I", 0xFEEF04BD))
    assert fixed % 4 == 0, "固定信息块按 4 字节对齐，否则系统读不出版本信息"


def test_icon_file_is_split_into_a_group_and_its_images():
    ico = (REPO / "assets" / "icon.ico").read_bytes()
    count = struct.unpack_from("<H", ico, 4)[0]
    group, images = make_launcher.icon_resources(ico)
    assert struct.unpack_from("<HHH", group, 0) == (0, 1, count)
    assert len(group) == 6 + 14 * count and [i for i, _ in images] == list(range(1, count + 1))
    assert all(image[:4] in (b"\x89PNG", b"\x28\x00\x00\x00") for _, image in images), \
        "每幅图像是 PNG 或 BMP 位图头"
    with pytest.raises(ValueError):
        make_launcher.icon_resources(b"not an icon file")


def test_launcher_is_only_built_inside_a_windows_virtualenv(monkeypatch):
    monkeypatch.setattr(make_launcher.sys, "platform", "linux")
    assert make_launcher.build() is None
    monkeypatch.setattr(make_launcher.sys, "platform", "win32")
    monkeypatch.setattr(make_launcher.sys, "prefix", make_launcher.sys.base_prefix)
    assert make_launcher.build() is None, "不在虚拟环境里：不往 Python 安装目录里写东西"


@windows_only
def test_rebranded_interpreter_reports_bigfish_and_still_runs(tmp_path):
    base = Path(sys.base_prefix)
    source = base / "pythonw.exe"
    core = base / f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    if not source.is_file() or not core.is_file():
        pytest.skip("这个 Python 布局里没有 pythonw.exe / 核心 DLL")
    import shutil

    target = tmp_path / "BigFish.exe"
    shutil.copy2(source, target)
    for dll in (core, *(base / name for name in make_launcher._RUNTIME_DLLS)):
        if dll.is_file():
            shutil.copy2(dll, tmp_path / dll.name)

    make_launcher.rebrand(target, "BigFish", (REPO / "assets" / "icon.ico").read_bytes(),
                          (*sys.version_info[:3], 0), "c")

    described = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"(Get-Item '{target}').VersionInfo.FileDescription"],
        capture_output=True, text=True, timeout=120).stdout.strip()
    assert described == "BigFish", "任务管理器显示的就是这个字段"
    kinds = {kind for kind, _name, _lang in make_launcher._existing_resources(
        target, (make_launcher.RT_ICON, make_launcher.RT_GROUP_ICON, make_launcher.RT_VERSION))}
    assert kinds == {make_launcher.RT_ICON, make_launcher.RT_GROUP_ICON, make_launcher.RT_VERSION}
    # 换了资源它仍然是个能跑的解释器（pythonw 没有控制台，用退出码回话）。和真实布局
    # 一样靠旁边的 pyvenv.cfg 找到标准库。
    (tmp_path / "pyvenv.cfg").write_text(f"home = {base}\n", encoding="utf-8")
    env ={k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "__PYVENV"))}
    ran = subprocess.run([str(target), "-I", "-c", "import sys; sys.exit(7)"], env=env, timeout=120)
    assert ran.returncode == 7


def test_run_bat_prefers_the_launcher_and_keeps_the_old_fallbacks():
    script = (REPO / "run.bat").read_text(encoding="utf-8")
    assert "tools\\make_launcher.py" in script
    assert script.index("BigFish.exe\" -m pet") < script.index("pythonw.exe\" -m pet") \
        < script.index("start \"\" pythonw -m pet")
