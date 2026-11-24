# -*- coding: utf-8 -*-
"""随手记落进个人知识库的收件箱（零 Qt、不调 AI、不碰 git）。

一条随手记 = ``0-Inbox/`` 下一个新文件（``YYYY-MM-DD HHMM <短名>.md``），图片放 ``0-Inbox/assets/``。**一条一个文件，
从不往已有文件里追加**：手机上的 Claude 会话和这台电脑可能同一分钟都在推，各写各的新文件就不会冲突。文件格式由知识库里的
``0-Inbox/README.md`` 规定；怎么整理成笔记由 ``9-Learning/Notes/README.md`` 规定（那份规矩在用户的私有库里，这里不认识）。

提交和推送不在这里：``personal_vault.sync_path`` 拿 ``write_capture`` 返回的那几个路径去 add / commit / push。
"""
from __future__ import annotations

import base64
import binascii
import datetime as dt
import json
import os
import re
from pathlib import Path

INBOX_DIR = "0-Inbox"
ASSETS_DIR = f"{INBOX_DIR}/assets"
NAME_CHARS = 24                   # 文件名里那段短名最多几个字：够认出是哪条，又不至于在 Obsidian 的列表里折行
MAX_IMAGES = 4                    # 一条最多几张图
MAX_IMAGE_BYTES = 3_000_000       # 一张图解码后最大多少字节：页面会把更大的先缩成 JPEG

#: 收的图片类型 → 扩展名、文件头。认文件头，不只信页面说的类型。
IMAGE_TYPES = {
    "image/png": (".png", (b"\x89PNG\r\n\x1a\n",)),
    "image/jpeg": (".jpg", (b"\xff\xd8\xff",)),
    "image/webp": (".webp", (b"RIFF",)),
    "image/gif": (".gif", (b"GIF87a", b"GIF89a")),
}

_URL_RE = re.compile(r"https?://[^\s<>\"'）】」]+")
_BAD_NAME_RE = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]+')


class CaptureError(ValueError):
    """页面发来的图片不收：``code`` 是 ``bad_image`` / ``too_many_images`` / ``image_too_large``。"""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def decode_images(items) -> list[tuple[str, bytes]]:
    """页面发来的 ``[{type, data(base64)}]`` → ``[(扩展名, 字节)]``。类型、文件头、大小、张数不对就抛 ``CaptureError``。"""
    if not items:
        return []
    if not isinstance(items, list):
        raise CaptureError("bad_image")
    if len(items) > MAX_IMAGES:
        raise CaptureError("too_many_images")
    out = []
    for item in items:
        kind = item.get("type") if isinstance(item, dict) else None
        data = item.get("data") if isinstance(item, dict) else None
        if kind not in IMAGE_TYPES or not isinstance(data, str):
            raise CaptureError("bad_image")
        if len(data) > (MAX_IMAGE_BYTES * 4) // 3 + 4:
            raise CaptureError("image_too_large")
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            raise CaptureError("bad_image") from None
        if len(raw) > MAX_IMAGE_BYTES:
            raise CaptureError("image_too_large")
        extension, magics = IMAGE_TYPES[kind]
        if not raw.startswith(magics):
            raise CaptureError("bad_image")
        out.append((extension, raw))
    return out


def source_of(text: str) -> str:
    """文字里的第一个链接就是出处；没有就空。"""
    match = _URL_RE.search(str(text or ""))
    return match.group(0) if match else ""


def short_name(text: str, fallback: str) -> str:
    """文件名里那段短名：第一行去掉链接和文件名里不能用的字符，压成单个空格，截到 ``NAME_CHARS``；剩不下字就用 ``fallback``。"""
    first = next((line for line in str(text or "").splitlines() if line.strip()), "")
    name = _BAD_NAME_RE.sub(" ", _URL_RE.sub(" ", first))
    name = " ".join(name.split())[:NAME_CHARS].strip().strip(".").strip()
    return name or fallback


def commit_message(now: dt.datetime) -> str:
    """提交说明只有时间，不带正文（提交记录和日志里都不出现记下的内容）。"""
    return f"capture: {now:%Y-%m-%d %H:%M}"


def _free_stem(inbox: Path, stem: str) -> str:
    """同一分钟同一句：后面加「 2」「 3」……，从不覆盖已有的那条。"""
    candidate, n = stem, 1
    while (inbox / f"{candidate}.md").exists():
        n += 1
        candidate = f"{stem} {n}"
    return candidate


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as handle:
        handle.write(data)
    os.replace(tmp, path)


def write_capture(repo_dir: str | Path, text: str, images: list[tuple[str, bytes]], now: dt.datetime, *,
                  fallback: str, via: str = "fish") -> list[str]:
    """把一条随手记写进收件箱：先写图片，最后写那条 ``.md``（中途失败不会留下指向不存在图片的笔记）。

    返回写下的文件（相对仓库、正斜杠），笔记在第一个，图片按顺序跟在后面。"""
    root = Path(repo_dir)
    body = "\n".join(line.rstrip() for line in str(text or "").strip().splitlines())
    stem = _free_stem(root / INBOX_DIR, f"{now:%Y-%m-%d %H%M} {short_name(body, fallback)}")
    pictures = []
    for index, (extension, data) in enumerate(images, start=1):
        name = f"{stem}-{index}{extension}"
        _write(root / ASSETS_DIR / name, data)
        pictures.append(name)
    head = (f"---\ncaptured: {now:%Y-%m-%d %H:%M}\nvia: {via}\nsource: {json.dumps(source_of(body), ensure_ascii=False)}\n"
            f"status: raw\n---\n\n")
    embeds = "".join(f"![[assets/{name}]]\n" for name in pictures)
    content = head + (body + "\n" if body else "") + ("\n" if body and embeds else "") + embeds
    note = f"{INBOX_DIR}/{stem}.md"
    _write(root / note, content.encode("utf-8"))
    return [note, *(f"{ASSETS_DIR}/{name}" for name in pictures)]
