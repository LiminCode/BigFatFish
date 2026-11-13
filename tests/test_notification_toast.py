# -*- coding: utf-8 -*-
"""Metro 通知弹窗：摆放（四个角 × 哪块屏）、叠放、排队、到点消失、点击 / 关闭 / 划走。

动画时长在测试里设成 0，计时器直接触发——测的是叠放和状态，不是时序。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pet import notification_center as nc
from pet import notification_toast as nt

app = QApplication.instance() or QApplication([])


def _notice(uid: int, **over) -> nc.Notice:
    base = dict(uid=uid, app="Demo App", app_id="Demo.App!App", title=f"Title {uid}", body=f"Body text {uid}",
                created=1_700_000_000.0 + uid)
    base.update(over)
    return nc.Notice(**base)


def _slack(uid: int, channel: str = "C1", title: str = "#general", **over) -> nc.Notice:
    base = dict(uid=uid, app="Slack", app_id="Slack!App", title=title, body=f"Ann: message {uid}",
                created=1_700_000_000.0 + uid, launch=f"slack://channel?id={channel}&message={uid}.0&team=T1",
                activation="protocol")
    base.update(over)
    return nc.Notice(**base)


# ---------------------------------------------------------------- 配置
def test_normalize_fills_defaults_and_clamps():
    assert nt.normalize(None) == nt.DEFAULTS
    out = nt.normalize({"corner": "nowhere", "screen": "  ", "seconds": 99999, "max_visible": 0, "theme": "x"})
    assert out == {**nt.DEFAULTS, "seconds": nt.SECONDS_RANGE[1], "max_visible": nt.MAX_VISIBLE_RANGE[0]}
    kept = nt.normalize({"corner": "bottom_left", "screen": r"\\.\DISPLAY2", "seconds": "8", "theme": "dark"})
    assert (kept["corner"], kept["screen"], kept["seconds"], kept["theme"]) == ("bottom_left", r"\\.\DISPLAY2", 8, "dark")


# ---------------------------------------------------------------- 摆放（纯函数）
AREA = QRect(100, 50, 1000, 400)        # 屏幕可用区：x 100..1099，y 50..449


@pytest.mark.parametrize("corner, first, second", [
    ("top_right", QPoint(1099 - 16 - 300 + 1, 50 + 16), QPoint(1099 - 16 - 300 + 1, 50 + 16 + 80 + 8)),
    ("top_left", QPoint(100 + 16, 50 + 16), QPoint(100 + 16, 50 + 16 + 80 + 8)),
    ("bottom_right", QPoint(1099 - 16 - 300 + 1, 450 - 16 - 80), QPoint(1099 - 16 - 300 + 1, 450 - 16 - 80 - 8 - 100)),
    ("bottom_left", QPoint(100 + 16, 450 - 16 - 80), QPoint(100 + 16, 450 - 16 - 80 - 8 - 100)),
])
def test_stack_positions_start_at_the_corner_and_grow_away_from_it(corner, first, second):
    positions = nt.stack_positions(AREA, corner, 300, [80, 100], margin=16, gap=8)
    assert positions == [first, second], "最新的贴着角，旧的往远离角的方向排"


def test_stack_positions_stop_when_the_screen_is_full():
    positions = nt.stack_positions(AREA, "top_right", 300, [150, 150, 150], margin=16, gap=8)
    assert len(positions) == 2, "第三张放不下就不给位置（留在队列里）"
    assert nt.stack_positions(AREA, "top_right", 300, [1000], margin=16, gap=8) == [QPoint(784, 66)], \
        "第一张再高也要给位置，不然一条都弹不出来"


class _Screen:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


def test_resolve_screen_by_name_cursor_or_primary():
    a, b, c = _Screen("A"), _Screen("B"), _Screen("C")
    assert nt.resolve_screen("B", [a, b, c], primary=a) is b
    assert nt.resolve_screen("gone", [a, b, c], primary=a) is a, "拔掉的屏退回主屏"
    assert nt.resolve_screen("primary", [a, b, c], primary=a) is a
    assert nt.resolve_screen("cursor", [a, b, c], primary=a, cursor=c) is c
    assert nt.resolve_screen("cursor", [a, b, c], primary=a, cursor=None) is a


def test_wrap_lines_elides_the_last_line():
    from PySide6.QtGui import QFont
    font = QFont()
    font.setPixelSize(13)
    lines = nt.wrap_lines("word " * 200, font, 200, 2)
    assert len(lines) == 2 and lines[-1].endswith("…")
    assert nt.wrap_lines("short", font, 200, 2) == ["short"]
    assert nt.wrap_lines("", font, 200, 2) == []


# ---------------------------------------------------------------- 叠放（Qt）
@pytest.fixture
def stack():
    s = nt.ToastStack(animate=False)
    s.apply_settings({"corner": "top_right", "screen": "primary", "seconds": 5, "max_visible": 3})
    yield s
    s.clear()
    app.processEvents()


def _area(stack):
    return stack.target_screen().availableGeometry()


def test_pushed_toasts_stack_from_the_chosen_corner(stack):
    for uid in (1, 2, 3):
        stack.push(_notice(uid))
    cards = stack.visible_cards()
    assert [c.notice.uid for c in cards] == [3, 2, 1], "最新的在最前（贴着角）"
    expected = nt.stack_positions(_area(stack), "top_right", nt.CARD_WIDTH, [c.height() for c in cards])
    assert [c.pos() for c in cards] == expected
    assert all(c.isVisible() for c in cards)


def test_reflow_reasserts_topmost_oldest_first_newest_last(stack):
    """实机 2026-11-02：卡片是从不激活的置顶工具窗，Qt 只在建窗时写一次 WS_EX_TOPMOST；被最大化的
    Electron 窗口（Windows 把它当全屏）盖住后再也不自己回来——屏幕上就「中间空一块」。每次重排都把在场的
    卡重新插回 topmost 带最上：老的先插、最新的最后插（在最上）。"""
    raised: list[int] = []
    stack._topmost = lambda card: raised.append(card.notice.uid) or True
    for uid in (1, 2, 3):
        stack.push(_notice(uid))
    assert raised[-3:] == [1, 2, 3]
    raised.clear()
    stack.visible_cards()[0].dismiss("closed")
    app.processEvents()
    assert raised == [1, 2], "一张走了重排：剩下的再插一遍"


def test_topmost_watchdog_runs_while_cards_are_shown_and_stops_after(stack):
    """没有新通知、没人走时也可能被盖住（用户点了最大化窗口）：在场期间每隔一会儿重插一次，没卡片就停。"""
    raised: list[int] = []
    stack._topmost = lambda card: raised.append(card.notice.uid) or True
    stack._watch.setInterval(10)
    stack.push(_notice(1))
    assert stack._watch.isActive()
    QTest.qWait(120)
    assert raised.count(1) >= 3
    stack.visible_cards()[0].dismiss("closed")
    app.processEvents()
    QTest.qWait(40)
    assert not stack._watch.isActive()


def test_reflow_uses_expanded_height_so_the_card_below_does_not_overlap(stack):
    """展开的一摞变高了，下面那张要按展开后的高度让位（原来按收起的高度算，会叠在一起）。"""
    for uid in (1, 2, 3, 4):
        stack.push(_slack(uid))
    stack.push(_notice(9))
    stack.push(_slack(5))                 # 同频道再来一条：这一摞挪回最上，单卡在它下面
    app.processEvents()
    group = next(c for c in stack.visible_cards() if c.is_group())
    single = next(c for c in stack.visible_cards() if not c.is_group())
    assert single.y() == group.y() + group.height() + nt.GAP
    group.set_expanded(True)
    app.processEvents()
    assert group.height() > nt.card_height(group.notices)
    assert single.y() == group.y() + group.height() + nt.GAP


def test_cards_dropped_off_the_end_of_the_queue_are_deleted(stack):
    """排队满了丢掉最旧的：它们藏着的卡片窗口也要删掉，不然「一直留着」时一天下来越积越多。"""
    import shiboken6
    from PySide6.QtCore import QEvent

    stack.apply_settings({"seconds": 0})
    cards = []
    for uid in range(nt._MAX_PENDING + 10):
        stack.push(_notice(uid))
        cards.append(stack._entries[0].card)              # 最新的马上弹，都有卡片
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    kept = {id(e.card) for e in stack._entries if e.card is not None}
    dropped = [c for c in cards if id(c) not in kept]
    assert len(dropped) == 10
    assert not any(shiboken6.isValid(c) for c in dropped), "丢掉的卡片窗口已删除"
    assert len(stack.visible_cards()) == 3


def test_more_than_max_visible_waits_and_shows_when_one_leaves(stack):
    for uid in (1, 2, 3, 4):
        stack.push(_notice(uid))
    assert [c.notice.uid for c in stack.visible_cards()] == [4, 3, 2]
    assert stack.queued_count() == 1
    stack.visible_cards()[0].dismiss("closed")
    app.processEvents()
    assert [c.notice.uid for c in stack.visible_cards()] == [3, 2, 1], "排队的补上来，剩下的往角那边挪"
    assert stack.queued_count() == 0


def test_expiry_dismisses_and_hover_pauses(stack):
    dismissed = []
    stack.dismissed.connect(lambda notice, reason: dismissed.append((notice.uid, reason)))
    stack.push(_notice(1))
    card = stack.visible_cards()[0]
    card.set_hovered(True)
    assert not card.timer_active(), "鼠标停着就不倒计时"
    card.set_hovered(False)
    assert card.timer_active()
    card.expire_now()
    app.processEvents()
    assert dismissed == [(1, "expired")]
    assert stack.visible_cards() == []


def test_click_activates_and_close_box_only_closes(stack):
    activated, dismissed = [], []
    stack.activated.connect(lambda notice: activated.append(notice.uid))
    stack.dismissed.connect(lambda notice, reason: dismissed.append((notice.uid, reason)))
    stack.push(_notice(1))
    stack.push(_notice(2))
    first, second = stack.visible_cards()
    QTest.mouseClick(first, Qt.MouseButton.LeftButton, pos=first.rect().center())
    app.processEvents()
    assert activated == [2] and dismissed == [(2, "activated")]
    QTest.mouseClick(second, Qt.MouseButton.LeftButton, pos=second.close_rect().center())
    app.processEvents()
    assert activated == [2] and dismissed[-1] == (1, "closed")


def test_swipe_toward_the_edge_dismisses(stack):
    dismissed = []
    stack.dismissed.connect(lambda notice, reason: dismissed.append(reason))
    stack.push(_notice(1))
    card = stack.visible_cards()[0]
    y = card.height() // 2
    QTest.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(20, y))
    QTest.mouseMove(card, QPoint(20 + nt.CARD_WIDTH // 2, y))
    QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=QPoint(20 + nt.CARD_WIDTH // 2, y))
    app.processEvents()
    assert dismissed == ["swiped"]


def test_changing_corner_moves_visible_cards(stack):
    stack.push(_notice(1))
    stack.apply_settings({"corner": "bottom_left"})
    card = stack.visible_cards()[0]
    assert card.pos() == nt.stack_positions(_area(stack), "bottom_left", nt.CARD_WIDTH, [card.height()])[0]


def test_same_uid_is_not_shown_twice(stack):
    stack.push(_notice(1))
    stack.push(_notice(1))
    assert len(stack.visible_cards()) == 1


# ---------------------------------------------------------------- 同一来源叠成一张（Slack 按频道）
def _uids(card):
    return [n.uid for n in card.notices]


def test_same_slack_channel_stacks_into_one_card_and_moves_back_to_the_corner(stack):
    stack.push(_slack(1))
    single = stack.visible_cards()[0].height()
    stack.push(_slack(2))
    cards = stack.visible_cards()
    assert len(cards) == 1 and _uids(cards[0]) == [2, 1], "同一频道：一张卡，最新的在上"
    assert cards[0].height() > single
    stack.push(_slack(3, channel="C2", title="#random"))
    assert [_uids(c) for c in stack.visible_cards()] == [[3], [2, 1]]
    stack.push(_slack(4))
    cards = stack.visible_cards()
    assert [_uids(c) for c in cards] == [[4, 2, 1], [3]], "这个频道又来了：整张卡回到最靠角的位置"
    expected = nt.stack_positions(_area(stack), "top_right", nt.CARD_WIDTH, [c.height() for c in cards])
    assert [c.pos() for c in cards] == expected


def test_group_card_shows_three_rows_and_counts_the_rest(stack):
    for uid in range(1, 6):
        stack.push(_slack(uid))
    card = stack.visible_cards()[0]
    assert card.row_count() == 3 and card.more_count() == 2


def test_other_apps_are_not_grouped(stack):
    stack.push(_notice(1))
    stack.push(_notice(2))
    assert [_uids(c) for c in stack.visible_cards()] == [[2], [1]]


def _click(card, pos):
    QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=pos)
    app.processEvents()


def test_clicking_a_stack_expands_it_instead_of_jumping(stack):
    activated, dismissed = [], []
    stack.activated.connect(lambda notice: activated.append(notice.uid))
    stack.dismissed.connect(lambda notice, reason: dismissed.append(reason))
    for uid in (1, 2, 3, 4, 5):
        stack.push(_slack(uid))
    card = stack.visible_cards()[0]
    collapsed_h = card.height()
    _click(card, card.row_rect(1).center())
    assert activated == [] and dismissed == [], "点一摞：展开，不跳、不收"
    assert card.expanded and card.height() > collapsed_h
    assert card.row_count() == 5, "展开后每条一行"
    assert not card.timer_active(), "展开着就一直留着"
    expected = nt.stack_positions(_area(stack), "top_right", nt.CARD_WIDTH, [card.height()])
    assert [card.pos()] == expected, "高度变了，位置跟着重排"


def test_clicking_a_row_of_an_expanded_stack_jumps_to_that_one_and_keeps_the_rest(stack):
    activated = []
    stack.activated.connect(lambda notice: activated.append(notice.uid))
    for uid in (1, 2, 3):
        stack.push(_slack(uid))
    card = stack.visible_cards()[0]
    _click(card, card.rect().center())
    _click(card, card.row_rect(1).center())
    assert activated == [2]
    assert stack.visible_cards() == [card] and _uids(card) == [3, 1], "跳走的那条拿掉，其余留着"
    assert card.expanded
    _click(card, card.row_rect(0).center())
    assert activated == [2, 3]
    assert _uids(card) == [1] and not card.expanded, "只剩一条：变回普通卡片"
    _click(card, card.rect().center())
    assert activated == [2, 3, 1] and stack.visible_cards() == []


def test_clicking_the_header_of_an_expanded_stack_collapses_it(stack):
    for uid in (1, 2, 3):
        stack.push(_slack(uid))
    card = stack.visible_cards()[0]
    _click(card, card.rect().center())
    assert card.expanded
    _click(card, QPoint(nt.CARD_WIDTH // 2, 20))
    assert not card.expanded and card.timer_active(), "收起后接着倒计时"


def test_stacking_choice_comes_from_settings(stack):
    stack.apply_settings({"stack": {"slack": "off"}})
    stack.push(_slack(1))
    stack.push(_slack(2))
    assert [_uids(c) for c in stack.visible_cards()] == [[2], [1]], "Slack 设成「每条单独」"


def test_chrome_notifications_stack_by_site(stack):
    def chrome(uid, site):
        return nc.Notice(uid=uid, app="Google Chrome", app_id="Chrome", title=f"t{uid}", body="b", created=uid,
                         launch=f"0|0|Default|0|https://{site}/|x", activation="foreground")

    stack.push(chrome(1, "mail.google.com"))
    stack.push(chrome(2, "calendar.google.com"))
    stack.push(chrome(3, "mail.google.com"))
    assert [_uids(c) for c in stack.visible_cards()] == [[3, 1], [2]]


def test_a_new_message_in_the_group_restarts_the_countdown(stack):
    stack.push(_slack(1))
    card = stack.visible_cards()[0]
    card.set_hovered(True)
    card._remaining_ms = 1500
    card.set_hovered(False)
    stack.push(_slack(2))
    assert card.timer_active() and card._timer.interval() == 5000


def test_zero_seconds_means_stay_until_dismissed(stack):
    stack.apply_settings({"seconds": 0})
    stack.push(_notice(1))
    card = stack.visible_cards()[0]
    assert not card.timer_active()
    card.set_hovered(True)
    card.set_hovered(False)
    assert not card.timer_active(), "一直留着，直到关掉"


# ---------------------------------------------------------------- 展开后每条消息一张小卡片、全文
_LONG = ("Ann: The quarterly picnic moved to the lakeside pavilion because the old meadow is flooded; "
         "bring a folding chair, a hat and something to share, and tell Bo whether you need a ride from the station.")
_LONG_ZH = "阿青: 周六的野餐改到湖边凉亭了，原来的草地积水没法用；请自带折叠椅和帽子，再带一样能分着吃的东西，需要从车站搭车的话提前跟小波说一声。"


def _squash(text: str) -> str:
    return "".join(str(text).split())


def test_wrap_full_keeps_every_character_and_breaks_long_tokens():
    font = nt._font(13)
    text = "see https://example.invalid/" + "a" * 200 + " then come back"
    lines = nt.wrap_full(text, font, 200)
    assert _squash("".join(lines)) == _squash(text), "全文都在，没有省略"
    assert len(lines) > 3 and not any("…" in line for line in lines)
    from PySide6.QtGui import QFontMetrics
    assert all(QFontMetrics(font).horizontalAdvance(line) <= 200 for line in lines), "没有空格的长串也要折开"
    assert nt.wrap_full("one\ntwo", font, 200) == ["one", "two"], "原文的换行保留"
    assert nt.wrap_full("", font, 200) == []


def test_expanded_stack_shows_every_message_in_full_in_its_own_block(stack):
    """实机 2026-11-12：展开后每条仍是单行、被省略号截断。展开 = 每条一张小卡片，正文折行显示全文。"""
    bodies = {1: _LONG, 2: _LONG_ZH, 3: "Bo: ok"}
    for uid, body in bodies.items():
        stack.push(_slack(uid, body=body))
    card = stack.visible_cards()[0]
    collapsed_h = card.height()
    _click(card, card.rect().center())
    assert card.expanded
    for index, notice in enumerate(card.notices):
        lines = card.row_lines(index)
        assert _squash("".join(lines)) == _squash(nc.split_body(bodies[notice.uid])[1]), "正文一个字不少"
        assert not any("…" in line for line in lines)
    assert len(card.row_lines(card.notices.index(next(n for n in card.notices if n.uid == 1)))) >= 3
    rects = [card.row_rect(i) for i in range(card.row_count())]
    assert all(a.bottom() < b.top() for a, b in zip(rects, rects[1:])), "小卡片一张接一张，不重叠"
    assert all(r.height() >= len(card.row_lines(i)) * nt._ROW_H for i, r in enumerate(rects)), "卡片随行数长高"
    assert card.height() > collapsed_h + 3 * nt._ROW_H
    assert card.height() == nt.card_height(card.notices, True), "不超屏时高度 = 内容高度"
    _click(card, QPoint(nt.CARD_WIDTH // 2, 20))
    assert not card.expanded and card.height() == collapsed_h, "收起态不变"


def test_expanded_stack_lists_every_message_without_a_more_line(stack):
    for uid in range(1, 13):
        stack.push(_slack(uid))
    card = stack.visible_cards()[0]
    assert (card.row_count(), card.more_count()) == (3, 9)
    card.set_expanded(True)
    assert (card.row_count(), card.more_count()) == (12, 0), "展开后全列出来，不再写「还有 N 条」"


def test_expanded_stack_never_outgrows_the_work_area_and_scrolls_instead(stack):
    activated = []
    stack.activated.connect(lambda notice: activated.append(notice.uid))
    for uid in range(1, nt._MAX_GROUP + 1):
        stack.push(_slack(uid, body=_LONG))
    card = stack.visible_cards()[0]
    card.set_expanded(True)
    app.processEvents()
    area = _area(stack)
    assert nt.card_height(card.notices, True) > area.height(), "这组内容本身比屏幕高"
    assert card.height() == area.height() - 2 * nt.MARGIN
    assert area.contains(card.geometry()), "卡片整个在工作区里"
    last = card.row_count() - 1
    assert card.scroll_max() > 0 and card.row_at(card.row_rect(last).center()) == -1, "最后一条在视口外，点不到"
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtCore import QPointF
    centre = QPointF(card.rect().center())
    wheel = QWheelEvent(centre, card.mapToGlobal(centre), QPoint(0, 0), QPoint(0, -120), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    app.sendEvent(card, wheel)
    assert 0 < card.scroll_offset() < card.scroll_max(), "滚轮往下：内容上移"
    card.scroll_to(10 ** 6)
    assert card.scroll_offset() == card.scroll_max()
    assert card.viewport_rect().contains(card.row_rect(last)), "滚到底：最后一条完整可见"
    _click(card, card.row_rect(last).center())
    assert activated == [1], "滚动后点到的还是那一条（最旧的在最下面）"
    assert card.scroll_offset() <= card.scroll_max(), "少了一条：滚动位置收回范围内"
    card.set_expanded(False)
    assert card.scroll_offset() == 0


def test_card_height_takes_a_ceiling_only_when_expanded():
    notices = [_slack(uid, body=_LONG) for uid in range(1, 11)]
    full = nt.card_height(notices, True)
    assert nt.card_height(notices, True, max_height=300) == 300 < full
    assert nt.card_height(notices, True, max_height=10 ** 6) == full
    assert nt.card_height(notices, False, max_height=10) == nt.card_height(notices, False), "收起态不受限高影响"
