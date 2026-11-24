# -*- coding: utf-8 -*-
"""随手记落进知识库的收件箱（``pet/capture_inbox.py``）：一条一个文件、图片放 assets、文件名、出处、图片的检查。

格式对齐知识库里那份收件箱说明（``0-Inbox/README.md``）。纪律：只写临时目录；样例文字中性、虚构。
"""
from __future__ import annotations

import base64
import datetime as dt

import pytest

from pet import capture_inbox as ci

NOW = dt.datetime(2026, 11, 24, 21, 5)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16


def test_a_text_capture_is_one_raw_file_in_the_inbox(tmp_path):
    paths = ci.write_capture(tmp_path, "  周末把阳台的旧书理一理\n第二行细节  ", [], NOW, fallback="随手记")
    assert paths == ["0-Inbox/2026-11-24 2105 周末把阳台的旧书理一理.md"]
    text = (tmp_path / paths[0]).read_bytes().decode("utf-8")
    assert text == ("---\ncaptured: 2026-11-24 21:05\nvia: fish\nsource: \"\"\nstatus: raw\n---\n\n"
                    "周末把阳台的旧书理一理\n第二行细节\n")
    assert "\r" not in text


def test_the_first_link_is_the_source_and_not_the_file_name(tmp_path):
    paths = ci.write_capture(tmp_path, "https://example.com/post/42?a=1 讲习惯叠加的一帖", [], NOW, fallback="随手记")
    assert paths == ["0-Inbox/2026-11-24 2105 讲习惯叠加的一帖.md"]
    text = (tmp_path / paths[0]).read_text(encoding="utf-8")
    assert 'source: "https://example.com/post/42?a=1"\n' in text
    only_link = ci.write_capture(tmp_path, "https://example.com/x", [], NOW, fallback="随手记")
    assert only_link == ["0-Inbox/2026-11-24 2105 随手记.md"]


def test_images_go_to_assets_and_are_embedded_after_the_text(tmp_path):
    paths = ci.write_capture(tmp_path, "截图里的一段话", [(".png", PNG), (".jpg", JPEG)], NOW, fallback="随手记")
    note, first, second = paths
    assert note == "0-Inbox/2026-11-24 2105 截图里的一段话.md"
    assert first == "0-Inbox/assets/2026-11-24 2105 截图里的一段话-1.png" and second.endswith("-2.jpg")
    assert (tmp_path / first).read_bytes() == PNG and (tmp_path / second).read_bytes() == JPEG
    text = (tmp_path / note).read_text(encoding="utf-8")
    assert text.endswith("截图里的一段话\n\n![[assets/2026-11-24 2105 截图里的一段话-1.png]]\n"
                         "![[assets/2026-11-24 2105 截图里的一段话-2.jpg]]\n")
    picture_only = ci.write_capture(tmp_path, "   ", [(".png", PNG)], NOW, fallback="截图")
    assert picture_only[0] == "0-Inbox/2026-11-24 2105 截图.md"


def test_the_same_minute_never_overwrites(tmp_path):
    first = ci.write_capture(tmp_path, "同一句", [], NOW, fallback="随手记")
    second = ci.write_capture(tmp_path, "同一句", [(".png", PNG)], NOW, fallback="随手记")
    assert first == ["0-Inbox/2026-11-24 2105 同一句.md"]
    assert second == ["0-Inbox/2026-11-24 2105 同一句 2.md", "0-Inbox/assets/2026-11-24 2105 同一句 2-1.png"]
    assert (tmp_path / first[0]).read_text(encoding="utf-8").endswith("同一句\n")


def test_file_names_drop_characters_windows_and_obsidian_cannot_take_and_stay_short(tmp_path):
    (path,) = ci.write_capture(tmp_path, 'a/b\\c:d*e?f"g<h>i|j#k^l[m]n. 很长很长很长很长很长很长很长很长很长很长的一句', [], NOW,
                               fallback="随手记")
    name = path.split("/")[-1][len("2026-11-24 2105 "):-len(".md")]
    assert not set(name) & set('/\\:*?"<>|#^[]') and len(name) <= ci.NAME_CHARS
    assert name == "a b c d e f g h i j k l", "不能用的字符换成空格、压成一个，截到 NAME_CHARS 再去掉尾巴上的空格"


def test_the_commit_message_carries_no_text():
    assert ci.commit_message(NOW) == "capture: 2026-11-24 21:05"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_images_from_the_page_are_decoded_and_checked():
    assert ci.decode_images([{"type": "image/png", "data": _b64(PNG)}, {"type": "image/jpeg", "data": _b64(JPEG)}]) == \
        [(".png", PNG), (".jpg", JPEG)]
    assert ci.decode_images(None) == [] and ci.decode_images([]) == []
    cases = {
        "bad_image": [[{"type": "image/png", "data": "not base64!"}], [{"type": "image/svg+xml", "data": _b64(b"<svg/>")}],
                      [{"type": "image/png", "data": _b64(JPEG)}], ["x"], "x"],
        "too_many_images": [[{"type": "image/png", "data": _b64(PNG)}] * (ci.MAX_IMAGES + 1)],
        "image_too_large": [[{"type": "image/png", "data": _b64(PNG + b"\x00" * ci.MAX_IMAGE_BYTES)}]],
    }
    for code, bodies in cases.items():
        for body in bodies:
            with pytest.raises(ci.CaptureError) as caught:
                ci.decode_images(body)
            assert caught.value.code == code, body


def test_the_local_service_accepts_a_request_with_the_most_images_allowed():
    from pet.panorama import server
    assert server.MAX_BODY >= ci.MAX_IMAGES * ci.MAX_IMAGE_BYTES * 4 // 3 + 64 * 1024, "base64 胀 4/3，再留文字的余量"
