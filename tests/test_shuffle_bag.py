# -*- coding: utf-8 -*-
"""洗牌式抽取：彩蛋弹窗的图、自言自语的配图与台词，一轮之内不重复。

实机现象：点几次就看到重复的图，台词更是来回那几句——三处都是每次独立地
``random.choice``。这里钉住洗牌的规则（一轮不重复、重洗不接连重复、牌堆变化时
怎么处理）、进度落盘（重启接着出），以及三处调用点真的在用它。

纪律：offscreen；进程级状态表由本文件的 autouse fixture 逐测清空（只在本文件里清：
往 conftest 加全局 autouse fixture 会改变整套用例的对象回收时机，实测能把一个潜伏的
Qt 原生崩溃引出来——哪怕 fixture 体只有一个 yield）。
"""
from __future__ import annotations

import json
import os
import random
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from pet import shuffle_bag
from pet import window_alerts as alerts
from pet.shuffle_bag import ShuffleStore

app = QApplication.instance() or QApplication([])

CARDS = [f"card-{i}" for i in range(7)]


@pytest.fixture(autouse=True)
def _fresh_store():
    shuffle_bag.STORE.reset()
    yield
    shuffle_bag.STORE.reset()


def _store(seed: int = 1) -> ShuffleStore:
    return ShuffleStore(random.Random(seed))


# ---------------------------------------------------------------- 规则
def test_every_card_comes_up_once_before_any_repeats():
    store = _store()
    for _round in range(5):
        assert sorted(store.draw("deck", CARDS) for _ in CARDS) == sorted(CARDS)


def test_a_reshuffle_never_starts_with_the_card_just_shown():
    for seed in range(60):
        store = _store(seed)
        drawn = [store.draw("deck", CARDS) for _ in range(len(CARDS) * 6)]
        assert all(a != b for a, b in zip(drawn, drawn[1:])), f"seed {seed} 出现接连重复"


def test_order_is_shuffled_not_the_listing_order():
    orders = set()
    for seed in range(20):
        store = _store(seed)
        orders.add(tuple(store.draw("deck", CARDS) for _ in CARDS))
    assert len(orders) >= 15, "不同的随机种子给出不同的顺序"
    assert tuple(CARDS) not in orders, "不是照着清单的顺序发"


def test_single_card_and_empty_decks():
    store = _store()
    assert [store.draw("one", ["only"]) for _ in range(3)] == ["only"] * 3
    assert store.draw("none", []) is None


def test_new_cards_join_the_current_round_and_removed_ones_drop_out():
    store = _store()
    first_three = [store.draw("deck", CARDS) for _ in range(3)]
    grown = [*CARDS, "newcomer"]
    rest = [store.draw("deck", grown) for _ in range(5)]
    assert "newcomer" in rest, "新加的图这一轮就轮得到"
    assert set(first_three).isdisjoint(rest), "已经出过的不会因为加了新图而重出"
    assert sorted(first_three + rest) == sorted(grown)

    shrunk = [c for c in grown if c != "card-0"]
    assert "card-0" not in [store.draw("deck", shrunk) for _ in range(len(shrunk) * 2)]


def test_decks_are_independent():
    store = _store()
    a = [store.draw("a", CARDS) for _ in range(3)]
    assert sorted(store.draw("b", CARDS) for _ in CARDS) == sorted(CARDS), "别的牌堆出过什么不影响这一副"
    assert set(a).isdisjoint(store.draw("a", CARDS) for _ in range(4))


def test_a_card_that_could_not_be_shown_goes_back_on_top():
    store = _store()
    skipped = store.draw("deck", CARDS)
    store.put_back("deck", skipped)
    assert store.draw("deck", CARDS) == skipped
    store.put_back("deck", "never-drawn")        # 没出过的牌：无事发生
    assert sorted([skipped, *(store.draw("deck", CARDS) for _ in range(6))]) == sorted(CARDS)


def test_old_decks_are_forgotten_beyond_the_limit():
    store = _store()
    for index in range(shuffle_bag.MAX_DECKS + 5):
        store.draw(f"deck-{index}", CARDS)
    assert store.state("deck-0") is None and store.state(f"deck-{shuffle_bag.MAX_DECKS + 4}")


# ---------------------------------------------------------------- 落盘
def test_progress_survives_a_restart(tmp_path):
    path = tmp_path / shuffle_bag.STATE_FILE_NAME
    before = _store()
    before.attach(path)
    shown = [before.draw("deck", CARDS) for _ in range(4)]
    saved = json.loads(path.read_text(encoding="utf-8"))["decks"]["deck"]
    assert saved["seen"] == shown and saved["last"] == shown[-1] and len(saved["queue"]) == 3

    after = _store(seed=99)                      # 重启：另一个进程、另一套随机数
    after.attach(path)
    rest = [after.draw("deck", CARDS) for _ in range(3)]
    assert sorted(shown + rest) == sorted(CARDS), "接着上一轮出，不把刚看过的再发一遍"


def test_missing_or_corrupt_state_file_just_starts_fresh(tmp_path):
    path = tmp_path / "sub" / shuffle_bag.STATE_FILE_NAME
    store = _store()
    store.attach(path)                           # 文件不存在
    assert store.draw("deck", CARDS) in CARDS and path.is_file(), "目录不存在会自己建"
    path.write_text("{ not json", encoding="utf-8")
    again = _store()
    again.attach(path)
    assert again.draw("deck", CARDS) in CARDS


def test_without_a_file_nothing_is_written(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = _store()
    for _ in range(10):
        store.draw("deck", CARDS)
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- 牌堆的键
def test_images_are_one_deck_per_directory_and_texts_one_per_wording(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    images = [a / "1.png", a / "2.gif"]
    assert shuffle_bag.deck_key("popup", images) == f"popup|{a}"
    assert shuffle_bag.deck_key("popup", [b / "1.png"]) != shuffle_bag.deck_key("popup", images)
    assert shuffle_bag.deck_key("t", ["甲", "乙"]) == shuffle_bag.deck_key("t", ["乙", "甲"])
    assert shuffle_bag.deck_key("t", ["甲", "乙"]) != shuffle_bag.deck_key("t", ["甲", "丙"])
    assert shuffle_bag.draw("popup", images) in images, "出的是路径本身"
    assert shuffle_bag.STORE.state(f"popup|{a}")["seen"][0] in ("1.png", "2.gif"), "牌堆里按文件名记"


# ---------------------------------------------------------------- 调用点
TEXTS = ["好女孩……", "好模型……", "欧鲸鲸……", "今天也要认真工作呀。", "再陪你一会儿。"]


def test_self_talk_lines_do_not_repeat_within_a_round():
    for _round in range(4):
        picks = [alerts.pick_self_talk_choice(TEXTS, [], 0) for _ in TEXTS]
        assert all(kind == "text" for kind, _ in picks)
        assert sorted(value for _, value in picks) == sorted(TEXTS)


def test_self_talk_images_do_not_repeat_within_a_round(tmp_path):
    images = [tmp_path / f"{i}.png" for i in range(6)]
    picks = [alerts.pick_self_talk_choice([], images, 100)[1] for _ in images]
    assert sorted(picks) == images


def test_image_chance_still_decides_between_image_and_text(monkeypatch):
    monkeypatch.setattr(alerts.random, "random", lambda: 0.10)      # 掷出 10
    assert alerts.pick_self_talk_choice(TEXTS, ["a.png"], 30)[0] == "image"
    monkeypatch.setattr(alerts.random, "random", lambda: 0.90)
    assert alerts.pick_self_talk_choice(TEXTS, ["a.png"], 30)[0] == "text"


def test_undecoded_image_falls_back_to_a_shuffled_line_and_is_shown_next(tmp_path):
    """配图还没解码好：改出台词，但不再固定是第一句；那张图放回去，下次先出它。"""
    images = [tmp_path / f"{i}.png" for i in range(5)]
    skipped = alerts.pick_self_talk_choice(TEXTS, images, 100)[1]

    fallbacks = [alerts.fallback_self_talk_text(TEXTS, images, skipped)]
    assert alerts.pick_self_talk_choice(TEXTS, images, 100)[1] == skipped

    for _ in range(4):
        fallbacks.append(alerts.fallback_self_talk_text(TEXTS, images, skipped))
    assert sorted(fallbacks) == sorted(TEXTS), "回退的台词也走洗牌，不是每次都第一句"
    assert alerts.fallback_self_talk_text([], images, skipped) is None


def test_click_bound_lines_are_shuffled_too():
    class Config:
        def get(self, _key, default=None):
            return default

        def click_talk_texts_for(self, _character, _click):
            return ["甲", "乙", "丙"]

    class Host:
        cfg = Config()
        shown: list = []

        def _show_self_talk_text(self, text):
            self.shown.append(text)
            return False        # 不朗读

    host = Host()
    for _ in range(6):
        alerts.show_click_self_talk(host, "点击回应-开心跃动")
    assert sorted(host.shown[:3]) == sorted(host.shown[3:]) == sorted(["甲", "乙", "丙"])
    assert host.shown[2] != host.shown[3]


def test_popup_goes_through_the_whole_folder_before_repeating(tmp_path):
    import pet.fun_image_popup as popup_mod

    for index in range(5):
        Image.new("RGB", (40, 30), (index * 40, 90, 160)).save(tmp_path / f"meme-{index}.png")
    manager = popup_mod.OjingjingWindowManager()
    try:
        opened = [manager.open_window(show=False, config={"image_dir": str(tmp_path)})
                  for _ in range(10)]
        names = [Path(w.property("sourceImage")).name for w in opened]
        assert sorted(names[:5]) == sorted(names[5:]) == [f"meme-{i}.png" for i in range(5)]
        assert names[4] != names[5]
    finally:
        manager.close_all()
        app.processEvents()


def test_startup_attaches_the_state_file_and_exit_lets_go_of_it():
    source = (Path(__file__).resolve().parent.parent / "pet" / "app.py").read_text(encoding="utf-8")
    attach = source.index("shuffle_bag.STORE.attach(config_dir / shuffle_bag.STATE_FILE_NAME)")
    assert source.index("acquire_overlay_instance_gate(config_dir)") < attach,         "过了单实例门才接上：被拒的第二实例不碰状态文件"
    assert source.index("shuffle_bag.STORE.detach()") > attach


def test_detach_keeps_the_round_in_memory_but_stops_writing(tmp_path):
    path = tmp_path / shuffle_bag.STATE_FILE_NAME
    store = _store()
    store.attach(path)
    shown = [store.draw("deck", CARDS) for _ in range(3)]
    written = path.read_text(encoding="utf-8")
    store.detach()
    rest = [store.draw("deck", CARDS) for _ in range(4)]
    assert sorted(shown + rest) == sorted(CARDS) and path.read_text(encoding="utf-8") == written


@pytest.mark.parametrize("count", [5, 35])
def test_repeat_rate_is_zero_within_a_round(count):
    """对照：独立随机抽 35 张连开 8 次有 58% 的概率重复；洗牌式一轮内是 0。"""
    cards = [f"c{i}" for i in range(count)]
    store = _store()
    drawn = [store.draw("deck", cards) for _ in range(count)]
    assert len(set(drawn)) == count
