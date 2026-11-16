# -*- coding: utf-8 -*-
"""配置全景的发布台：存最近一次发布的数据，并让「等新数据」的请求等到有为止。

时序用线程 + join 断言结果，不赌先后：先发布再等、先等再发布，等的人拿到的都该是同一份。
"""
from __future__ import annotations

import threading

from pet.panorama.feed import Feed

WAIT = 15.0


def _in_thread(fn):
    box = {}
    thread = threading.Thread(target=lambda: box.setdefault("result", fn()), daemon=True)
    thread.start()
    return thread, box


def test_nothing_is_published_at_first():
    feed = Feed()
    assert feed.revision == 0 and feed.latest() is None


def test_each_publish_gets_the_next_revision_and_replaces_the_payload():
    feed = Feed()
    seen = []
    assert feed.publish(lambda revision: seen.append(revision) or b"one") == 1
    assert feed.publish(lambda revision: seen.append(revision) or b"two") == 2
    assert seen == [1, 2] and feed.revision == 2 and feed.latest() == b"two"     # 构造函数拿到的就是它将得到的编号


def test_waiting_returns_at_once_when_something_newer_is_already_there():
    feed = Feed()
    feed.publish(lambda revision: b"one")
    assert feed.wait_newer(0, timeout=WAIT) == b"one"


def test_waiting_times_out_with_nothing_when_no_one_publishes():
    feed = Feed()
    feed.publish(lambda revision: b"one")
    assert feed.wait_newer(1, timeout=0.05) is None
    assert feed.wait_newer(7, timeout=0.05) is None                               # 页面记的编号比这里还新（服务重启过）：也只是等


def test_a_waiter_is_woken_by_the_next_publish():
    feed = Feed()
    feed.publish(lambda revision: b"one")
    thread, box = _in_thread(lambda: feed.wait_newer(1, timeout=WAIT))
    feed.publish(lambda revision: b"two")
    thread.join(WAIT)
    assert not thread.is_alive() and box["result"] == b"two"


def test_every_waiter_gets_the_new_payload():
    feed = Feed()
    waiters = [_in_thread(lambda: feed.wait_newer(0, timeout=WAIT)) for _ in range(5)]
    feed.publish(lambda revision: b"one")
    for thread, box in waiters:
        thread.join(WAIT)
        assert not thread.is_alive() and box["result"] == b"one"


def test_feed_knows_how_many_are_waiting():
    import time

    feed = Feed()
    assert feed.waiting == 0
    waiters = [_in_thread(lambda: feed.wait_newer(0, timeout=WAIT)) for _ in range(3)]
    deadline = time.monotonic() + WAIT
    while feed.waiting < 3 and time.monotonic() < deadline:      # 轮询状态、预算给宽，不赌线程多久能跑到
        time.sleep(0.005)
    assert feed.waiting == 3
    feed.publish(lambda revision: b"one")
    for thread, _box in waiters:
        thread.join(WAIT)
    assert feed.waiting == 0


def test_closing_releases_waiters_and_later_waits_do_not_block():
    """退出应用时不能有请求还挂在这里。"""
    feed = Feed()
    feed.publish(lambda revision: b"one")
    thread, box = _in_thread(lambda: feed.wait_newer(1, timeout=WAIT))
    feed.close()
    thread.join(WAIT)
    assert not thread.is_alive() and box["result"] is None
    assert feed.wait_newer(1, timeout=WAIT) is None and feed.closed              # 关了以后立刻返回，不等满
    assert feed.latest() == b"one"                                               # 已发布的那份还在


def test_feed_module_stays_stdlib_only():
    import ast
    import sys
    from pathlib import Path

    from pet.panorama import feed as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            imported.add((node.module or "").split(".")[0])
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}, sorted(imported)
