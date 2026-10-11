"""生成源码运行用的启动器 ``.venv\\Scripts\\BigFish.exe``（仅 Windows）。

为什么要有它：从源码跑（``run.bat``）时进程是 ``pythonw.exe``，任务管理器里显示成
「Python」、用的是 Python 的图标——任务管理器的进程名取自 exe 的版本资源
（FileDescription），不是窗口标题，程序自己改不了。唯一的办法是换一个 exe。

做法：把基础解释器的 ``pythonw.exe`` 复制一份，改掉它的版本资源（名字）与图标资源，
连同它启动要用的几个 DLL 放进虚拟环境的 ``Scripts`` 目录。它旁边的上一级有
``pyvenv.cfg``，所以照样按这个虚拟环境找包——而且是解释器本身，不再是「启动器 +
真解释器」两个进程。

它仍然是 Python 解释器，只是换了名字和图标；改过资源后原有的数字签名不再有效
（不影响运行）。只改复制出来的这一份，Python 安装目录里的文件不动。

用法::

    python tools/make_launcher.py            # 需要时（缺失 / 解释器或图标变了）才重新生成
    python tools/make_launcher.py --force

打包版（PyInstaller）不走这里：它本来就是自己的 exe。
"""
from __future__ import annotations

import ctypes
import json
import shutil
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP_NAME = "BigFish"
ICON = REPO / "assets" / "icon.ico"
#: 基础解释器启动时必须在 exe 旁边找得到的 DLL（没有的跳过）
_RUNTIME_DLLS = ("python3.dll", "vcruntime140.dll", "vcruntime140_1.dll")

RT_ICON, RT_GROUP_ICON, RT_VERSION = 3, 14, 16
_LANG_EN_US = 0x0409


# ---------------------------------------------------------------- 版本资源
def _pad4(data: bytearray) -> bytearray:
    data += b"\0" * (-len(data) % 4)
    return data


def _node(key: str, value: bytes = b"", value_len: int = 0, wtype: int = 1,
          children: tuple[bytes, ...] = ()) -> bytes:
    """VS_VERSIONINFO 的一个节点：长度头 + UTF-16 键 + 值 + 子节点，全部按 4 字节对齐。"""
    data = _pad4(bytearray(6) + (key + "\0").encode("utf-16le"))
    data += value
    for child in children:
        data = _pad4(data)
        data += child
    struct.pack_into("<HHH", data, 0, len(data), value_len, wtype)
    return bytes(data)


def _string(key: str, value: str) -> bytes:
    return _node(key, (value + "\0").encode("utf-16le"), len(value) + 1, 1)


def version_resource(name: str, version: tuple[int, int, int, int], *, copyright_text: str) -> bytes:
    """名字为 ``name`` 的 RT_VERSION 资源（任务管理器的进程名取其中的 FileDescription）。"""
    major, minor, micro, build = version
    ms, ls = (major << 16) | minor, (micro << 16) | build
    fixed = struct.pack("<13I", 0xFEEF04BD, 0x00010000, ms, ls, ms, ls,
                        0x3F, 0, 0x00040004, 1, 0, 0, 0)   # VOS_NT_WINDOWS32 / VFT_APP
    dotted = ".".join(str(part) for part in version)
    strings = _node("040904B0", children=(
        _string("CompanyName", name),
        _string("FileDescription", name),
        _string("FileVersion", dotted),
        _string("InternalName", name),
        _string("LegalCopyright", copyright_text),
        _string("OriginalFilename", f"{name}.exe"),
        _string("ProductName", name),
        _string("ProductVersion", dotted),
    ))
    return _node("VS_VERSION_INFO", fixed, len(fixed), 0, children=(
        _node("StringFileInfo", children=(strings,)),
        _node("VarFileInfo", children=(
            _node("Translation", struct.pack("<HH", _LANG_EN_US, 0x04B0), 4, 0),)),
    ))


# ---------------------------------------------------------------- 图标资源
def icon_resources(ico: bytes, first_id: int = 1) -> tuple[bytes, list[tuple[int, bytes]]]:
    """``.ico`` 文件 → (RT_GROUP_ICON 数据, [(RT_ICON 的 ID, 图像数据), …])。"""
    reserved, kind, count = struct.unpack_from("<HHH", ico, 0)
    if reserved != 0 or kind != 1 or count == 0:
        raise ValueError("不是有效的 .ico 文件")
    group = bytearray(struct.pack("<HHH", 0, 1, count))
    images: list[tuple[int, bytes]] = []
    for index in range(count):
        width, height, colors, _res, planes, bits, size, offset = struct.unpack_from(
            "<BBBBHHII", ico, 6 + 16 * index)
        icon_id = first_id + index
        group += struct.pack("<BBBBHHIH", width, height, colors, 0, planes, bits, size, icon_id)
        images.append((icon_id, ico[offset:offset + size]))
    return bytes(group), images


# ---------------------------------------------------------------- 写进 exe
def _existing_resources(path: Path, kinds: tuple[int, ...]) -> list[tuple[int, object, int]]:
    """exe 里已有的 ``(类型, 名字, 语言)``；名字是整数 ID 或字符串。"""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LoadLibraryExW.restype = ctypes.c_void_p
    kernel32.LoadLibraryExW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32]
    kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
    module = kernel32.LoadLibraryExW(str(path), None, 0x00000002 | 0x00000020)   # 只当数据文件
    if not module:
        raise ctypes.WinError(ctypes.get_last_error())
    found: list[tuple[int, object, int]] = []
    name_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_void_p, ctypes.c_void_p)
    lang_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_void_p, ctypes.c_uint16, ctypes.c_void_p)
    kernel32.EnumResourceNamesW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, name_proc,
                                            ctypes.c_void_p]
    kernel32.EnumResourceLanguagesW.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                ctypes.c_void_p, lang_proc, ctypes.c_void_p]
    try:
        for kind in kinds:
            names: list[object] = []

            def on_name(_module, _kind, name, _param, names=names):
                value = int(name or 0)
                names.append(value if value >> 16 == 0 else ctypes.wstring_at(value))
                return True

            kernel32.EnumResourceNamesW(module, kind, name_proc(on_name), None)
            for name in names:
                langs: list[int] = []

                def on_lang(_module, _kind, _name, lang, _param, langs=langs):
                    langs.append(int(lang))
                    return True

                raw = name if isinstance(name, int) else ctypes.c_wchar_p(name)
                kernel32.EnumResourceLanguagesW(module, kind, raw, lang_proc(on_lang), None)
                found.extend((kind, name, lang) for lang in langs)
    finally:
        kernel32.FreeLibrary(module)
    return found


def rebrand(path: Path, name: str, ico: bytes, version: tuple[int, int, int, int],
            copyright_text: str) -> None:
    """把 ``path`` 这个 exe 的图标与版本资源换成我们的。"""
    stale = _existing_resources(path, (RT_ICON, RT_GROUP_ICON, RT_VERSION))
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.BeginUpdateResourceW.restype = ctypes.c_void_p
    kernel32.BeginUpdateResourceW.argtypes = [ctypes.c_wchar_p, ctypes.c_bool]
    kernel32.UpdateResourceW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                         ctypes.c_uint16, ctypes.c_char_p, ctypes.c_uint32]
    kernel32.EndUpdateResourceW.argtypes = [ctypes.c_void_p, ctypes.c_bool]
    handle = kernel32.BeginUpdateResourceW(str(path), False)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    keep: list[object] = []      # 字符串名字的缓冲区要活到 EndUpdateResource

    def update(kind: int, res_name, lang: int, data: bytes | None) -> None:
        if isinstance(res_name, str):
            buffer = ctypes.create_unicode_buffer(res_name)
            keep.append(buffer)
            raw = ctypes.cast(buffer, ctypes.c_void_p)
        else:
            raw = ctypes.c_void_p(res_name)
        if not kernel32.UpdateResourceW(handle, kind, raw, lang, data, len(data or b"")):
            error = ctypes.get_last_error()
            kernel32.EndUpdateResourceW(handle, True)
            raise ctypes.WinError(error)

    for kind, res_name, lang in stale:           # 原有的图标 / 版本信息全部删掉
        update(kind, res_name, lang, None)
    group, images = icon_resources(ico)
    for icon_id, image in images:
        update(RT_ICON, icon_id, _LANG_EN_US, image)
    update(RT_GROUP_ICON, 1, _LANG_EN_US, group)
    update(RT_VERSION, 1, _LANG_EN_US,
           version_resource(name, version, copyright_text=copyright_text))
    if not kernel32.EndUpdateResourceW(handle, False):
        raise ctypes.WinError(ctypes.get_last_error())


# ---------------------------------------------------------------- 入口
def _signature(base_exe: Path, dlls: list[Path]) -> dict:
    files = [base_exe, ICON, Path(__file__), *dlls]
    return {str(f): [f.stat().st_size, int(f.stat().st_mtime)] for f in files if f.exists()}


def launcher_path() -> Path:
    return Path(sys.prefix) / "Scripts" / f"{APP_NAME}.exe"


def build(force: bool = False) -> Path | None:
    """生成（或确认已是最新的）启动器；不适用的环境返回 None。"""
    if sys.platform != "win32":
        return None
    if sys.prefix == sys.base_prefix:
        return None                    # 不在虚拟环境里：不往 Python 安装目录里写东西
    base_dir = Path(sys.base_prefix)
    base_exe = base_dir / "pythonw.exe"
    core_dll = base_dir / f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    if not base_exe.is_file() or not core_dll.is_file() or not ICON.is_file():
        return None
    dlls = [core_dll] + [base_dir / name for name in _RUNTIME_DLLS if (base_dir / name).is_file()]
    target = launcher_path()
    stamp = target.with_suffix(".json")
    signature = _signature(base_exe, dlls)
    if not force and target.is_file():
        try:
            if json.loads(stamp.read_text(encoding="utf-8")) == signature:
                return target
        except (OSError, ValueError):
            pass
    target.parent.mkdir(parents=True, exist_ok=True)
    for dll in dlls:
        shutil.copy2(dll, target.parent / dll.name)
    scratch = target.with_suffix(".tmp")
    shutil.copy2(base_exe, scratch)
    version = (*sys.version_info[:3], 0)
    rebrand(scratch, APP_NAME, ICON.read_bytes(), version,
            "Python interpreter (c) Python Software Foundation; relabelled for BigFish")
    scratch.replace(target)
    stamp.write_text(json.dumps(signature), encoding="utf-8")
    return target


def main() -> int:
    try:
        target = build(force="--force" in sys.argv)
    except OSError as exc:
        # 最常见：BigFish.exe 正在运行，文件被占用。不算错——继续用现有的那份。
        print(f"没有重新生成启动器（{exc}）")
        return 0
    if target is None:
        print("此环境不生成启动器（非 Windows / 不在虚拟环境里 / 缺少图标）")
        return 0
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
