# -*- coding: utf-8 -*-
"""Stable leaf-menu primitives shared by the two independent layouts."""
from __future__ import annotations

import logging
import threading

import shiboken6

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot
from PySide6.QtCore import QUrl
from PySide6.QtGui import QActionGroup, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import QMenu

from .. import autostart as autostart_mod
from .. import catalog
from .. import claude_hooks
from .. import claude_launchers
from .icons import fitted_pet_pixmap_icon, pet_avatar_menu_icon, vector_menu_icon
from .menu_styles.common import inherit_menu_style

log = logging.getLogger(__name__)

#: 「GitHub 项目页」打开的地址（上游仓库）
REPO_URL = "https://github.com/MerZlin/dsh-pet-indesktop"


class _AnimationIconSignals(QObject):
    ready = Signal(object)


class _AnimationIconWorker(QRunnable):
    def __init__(self, loader, animation_name: str):
        super().__init__()
        self.loader = loader
        self.animation_name = animation_name
        self.signals = _AnimationIconSignals()

    def run(self) -> None:
        self.signals.ready.emit(self.loader(self.animation_name))


class _AnimationIconApplier(QObject):
    """GUI 线程槽：接收 worker 解码完成信号并更新 QAction。

    挂在 submenu 下随菜单生命周期存在；worker 线程只负责解码，
    ready 信号经 Qt 自动队列投递到本对象（GUI 线程），避免跨线程
    操作 QMenu/QAction（Qt 未定义行为，可致偶发崩溃/图标错乱）。
    """

    def __init__(self, submenu, action, worker, pump, parent=None):
        super().__init__(parent)
        self._submenu = submenu
        self._action = action
        self._worker = worker
        self._pump = pump

    @Slot(object)
    def on_ready(self, image) -> None:
        submenu = self._submenu
        if shiboken6.isValid(submenu) is False:
            return
        if self._worker in submenu._animation_icon_workers:
            submenu._animation_icon_workers.remove(self._worker)
        # setIcon() invalidates QMenu's action geometry. Doing
        # that dozens of times on a visible, scrollable menu
        # corrupts its scroll layout and blocks hover events.
        if (
            not submenu.isVisible()
            and image is not None
            and not image.isNull()
        ):
            self._action.setIcon(fitted_pet_pixmap_icon(submenu, QPixmap.fromImage(image)))
            submenu.update()
        pump = self._pump
        if callable(pump):
            pump()


def _root_menu(menu: QMenu) -> QMenu:
    root = menu
    while isinstance(root.parent(), QMenu):
        root = root.parent()
    return root


def take_deferred_menu_callbacks(menu: QMenu) -> list:
    """Take commands that must run after the native menu tracking loop."""
    callbacks = list(getattr(menu, "_deferred_callbacks", ()))
    menu._deferred_callbacks = []
    return callbacks


def defer_menu_callback(menu: QMenu, callback) -> bool:
    """Run a command after native menu tracking ends when the menu is open."""
    if not menu.isVisible():
        callback()
        return False
    root = _root_menu(menu)
    root._deferred_callbacks = list(
        getattr(root, "_deferred_callbacks", ())
    ) + [callback]
    root.close()
    return True


def release_menu_tree(menu: QMenu) -> None:
    """释放整棵右键菜单树（``menu.exec()`` 返回后必须调用一次）。

    菜单以**长命窗口**为 parent，只丢 Python 引用时 C++ 侧的整棵树（子菜单/动作/
    动画图标解码池/图标 pixmap）会随每次右键永久累积——实测 offscreen 经 facade
    构建 modern 全量菜单 10 轮：+153 QMenu / +780 QAction；走本函数后增量 0。
    根因是 ``apply_modern_menu_style`` / ``install_modern_check_indicators`` 的
    ``aboutToShow.connect(lambda menu=menu: ...)`` 自引用连接让 Python 侧也永不
    释放（详见 ``tests/test_menu_tree_release.py``）。

    流程与 window.py 原实现逐位一致：

    1. 先 ``pool.clear()`` 掉各动画分类子菜单尚未启动的解码任务——否则
       QThreadPool 析构时会在 GUI 线程等运行中的 worker；
    2. 再有界轮询等 worker 收工（每 50ms 一次，总上限 3s，不阻塞事件循环；解码
       worker 病态不结束时也强制释放，否则菜单树永久滞留），然后
       ``menu.deleteLater()``。轮询定时器绑 menu 作 context：菜单先销毁时定时器
       随之失效，不会对已删 C++ 对象再 ``deleteLater``。
    """
    pools = []
    for submenu in menu.findChildren(QMenu):
        pool = getattr(submenu, "_animation_icon_pool", None)
        if pool is not None:
            pool.clear()
            pools.append(pool)

    def delete_when_idle(_attempts: int = 0) -> None:
        if _attempts >= 60:
            menu.deleteLater()
            return
        if any(not pool.waitForDone(0) for pool in pools):
            QTimer.singleShot(50, menu, lambda: delete_when_idle(_attempts + 1))
            return
        menu.deleteLater()

    if pools:
        delete_when_idle()
    else:
        menu.deleteLater()


def connect_action(action, callback) -> None:
    def invoke(_checked=False, action=action, callback=callback) -> None:
        parent = action.parent()
        if (
            bool(action.property("closeOnTrigger"))
            and isinstance(parent, QMenu)
            and parent.isVisible()
        ):
            defer_menu_callback(parent, callback)
            return
        callback()

    action.triggered.connect(invoke)


def add_action(
    menu: QMenu, text: str, icon_name: str | None, callback=None, *,
    close_on_trigger: bool = False,
):
    action = menu.addAction(vector_menu_icon(menu, icon_name) if icon_name else QIcon(), text)
    action.setProperty("closeOnTrigger", bool(close_on_trigger))
    if callback is not None:
        connect_action(action, callback)
    return action


def add_submenu(menu: QMenu, text: str, icon_name: str | None = None) -> QMenu:
    submenu = QMenu(text, menu)
    menu.addMenu(submenu)
    menu._owned_submenus = getattr(menu, "_owned_submenus", []) + [submenu]
    inherit_menu_style(menu, submenu)
    if icon_name:
        submenu.setIcon(vector_menu_icon(menu, icon_name))
    return submenu


def _populate_animation_category(
    submenu: QMenu, pet, entries, callback, leaf_role_icons: bool,
) -> None:
    """首次展开动画分类子菜单时才填充动作，避免根菜单构建时遍历 91 个动画。"""
    if getattr(submenu, "_animation_populated", False):
        return
    submenu._animation_populated = True

    icon_actions = []
    lazy_actions = []
    for name in entries:
        action = submenu.addAction(QIcon(), name) if leaf_role_icons else submenu.addAction(name)
        connect_action(action, lambda name=name, callback=callback: callback(name))
        if leaf_role_icons:
            icon_actions.append((action, name))
            cached_loader = getattr(pet, "animation_icon_cached_image", None)
            cached = cached_loader(name) if callable(cached_loader) else None
            if cached is not None and not cached.isNull():
                action.setIcon(fitted_pet_pixmap_icon(submenu, QPixmap.fromImage(cached)))
            else:
                # A neutral loading glyph avoids a blank/jumping text
                # column while the representative frame is decoded.
                action.setIcon(vector_menu_icon(submenu, "loading"))
                lazy_actions.append((action, name))

    if not lazy_actions:
        return

    # Decoding dozens of WebM frames while the root menu is being constructed
    # made the very first right-click block for seconds. Load only the category
    # the user actually opens in a two-thread pool and keep completed icons on
    # their QAction for later opens.
    def refresh_cached_icons(
        submenu=submenu, icon_actions=tuple(icon_actions), pet=pet,
    ) -> None:
        """Only alter QAction geometry before show or after hide."""
        # aboutToHide 会排队 singleShot 刷新，菜单可能已销毁
        if shiboken6.isValid(submenu) is False:
            return
        if submenu.isVisible():
            return
        cached_loader = getattr(pet, "animation_icon_cached_image", None)
        if not callable(cached_loader):
            return
        for action, animation_name in icon_actions:
            image = cached_loader(animation_name)
            if image is not None and not image.isNull():
                action.setIcon(fitted_pet_pixmap_icon(submenu, QPixmap.fromImage(image)))

    def start_loading(submenu=submenu, lazy_actions=tuple(lazy_actions), pet=pet) -> None:
        loader = getattr(pet, "animation_icon_image", None)
        if not callable(loader):
            return
        if not hasattr(submenu, "_animation_icon_pending"):
            submenu._animation_icon_pending = list(lazy_actions)
            submenu._animation_icon_requested = set()

        def pump() -> None:
            while (
                len(submenu._animation_icon_workers) < 2
                and submenu._animation_icon_pending
            ):
                action, animation_name = submenu._animation_icon_pending.pop(0)
                if animation_name in submenu._animation_icon_requested:
                    continue
                submenu._animation_icon_requested.add(animation_name)
                launch(action, animation_name)

        def launch(action, animation_name) -> None:
            worker = _AnimationIconWorker(loader, animation_name)
            # 解码完成信号经队列投递到 GUI 线程的 applier 槽：
            # 菜单销毁时连接随 applier（submenu 子对象）自动断开。
            applier = _AnimationIconApplier(
                submenu, action, worker, pump, parent=submenu
            )
            worker.signals.ready.connect(applier.on_ready)
            submenu._animation_icon_workers.append(worker)
            submenu._animation_icon_pool.start(worker)

        pump()

    submenu.aboutToShow.connect(refresh_cached_icons)
    submenu.aboutToShow.connect(start_loading)
    submenu.aboutToHide.connect(
        lambda refresh=refresh_cached_icons, submenu=submenu: QTimer.singleShot(0, submenu, refresh)
    )
    pool = QThreadPool(submenu)
    pool.setMaxThreadCount(2)
    submenu._animation_icon_pool = pool
    submenu._animation_icon_workers = []
    # 首次填充时立刻启动解码；后续 aboutToShow 继续由连接驱动
    start_loading()


def build_animation_categories(
    menu: QMenu, pet, *, icons: bool, legacy_labels: bool = False,
    leaf_role_icons: bool = False,
) -> None:
    categories = (
        ("待机", pet.idles, pet.switch_clip),
        ("转向", pet.turns, pet.switch_clip),
        ("移动", pet.moves, pet.trigger_move),
        ("点击回应", pet.clicks, pet.switch_clip),
        ("随机动作", pet.acts, pet.switch_clip),
    )
    for label, entries, callback in categories:
        if not entries:
            continue
        submenu = QMenu(f"动画 · {label}" if legacy_labels else label, menu)
        menu.addMenu(submenu)
        menu._owned_submenus = getattr(menu, "_owned_submenus", []) + [submenu]
        inherit_menu_style(menu, submenu)
        if icons:
            submenu.setIcon(vector_menu_icon(menu, "play"))
        # 首次展开该分类子菜单时才填充动作：根菜单构建不再遍历 91 个动画
        submenu.aboutToShow.connect(
            lambda s=submenu, e=entries, c=callback, l=leaf_role_icons, p=pet:
                _populate_animation_category(s, p, e, c, l)
        )


def build_speed_menu(menu: QMenu, pet, *, icons: bool = True) -> QMenu:
    submenu = add_submenu(menu, "播放速率", "speed" if icons else None)
    group = QActionGroup(submenu)
    group.setExclusive(True)
    for i in range(10, 21):
        value = i / 10.0
        action = submenu.addAction(f"{value:.1f}x")
        action.setCheckable(True)
        action.setChecked(abs(pet.playback_speed - value) < 0.01)
        group.addAction(action)
        connect_action(action, lambda value=value: pet.set_playback_speed(value))
    return submenu


def build_character_menu(menu: QMenu, pet, *, icons: bool = True) -> QMenu:
    submenu = add_submenu(menu, "切换角色", "character" if icons else None)
    group = QActionGroup(submenu)
    group.setExclusive(True)
    current = str(pet.cfg.get("character", catalog.DEFAULT_CHARACTER))
    for character_id in catalog.list_available_characters():
        alias_fn = getattr(pet.cfg, 'character_alias', None)
        alias = alias_fn(character_id) if callable(alias_fn) else ''
        label = alias or catalog.character_display_name(character_id)
        action = submenu.addAction(label)
        action.setCheckable(True)
        action.setChecked(character_id == current)
        group.addAction(action)
        action.setProperty("closeOnTrigger", True)
        connect_action(action, lambda character_id=character_id: pet.request_switch_character(character_id))
    # 角色显示名别名（空名恢复默认）
    rename = getattr(pet, "rename_character", None)
    if callable(rename):
        submenu.addSeparator()
        add_action(submenu, "重命名当前角色…", None, rename, close_on_trigger=True)
    return submenu


def add_proactive_menu(menu: QMenu, pet) -> None:
    """主动识屏二级菜单（仅 Windows 且有聊天/视觉能力时显示）。"""
    import sys as _sys
    if _sys.platform != 'win32':
        return
    if getattr(pet, 'on_open_chat', None) is None:
        return
    from ..proactive import effective_proactive_config

    sub = add_submenu(menu, "主动识屏", None)
    pro_cfg = effective_proactive_config(pet.cfg.get('proactive_screen', {}))

    def _toggle(text, checked, handler):
        act = sub.addAction(text)
        act.setCheckable(True)
        act.setChecked(bool(checked))
        act.toggled.connect(handler)
        return act

    _toggle('开启主动识屏', pro_cfg.get('enabled', False), pet.toggle_proactive_enabled)
    _toggle('鼠标穿透时仍允许主动识屏', pro_cfg.get('allow_when_mouse_through', True),
            lambda on: pet.set_proactive_option('allow_when_mouse_through', on))
    _toggle('触发前先兆提示', pro_cfg.get('pre_cue', True),
            lambda on: pet.set_proactive_option('pre_cue', on))
    _toggle('仅当我闲置时触发', pro_cfg.get('require_idle', False),
            lambda on: pet.set_proactive_option('require_idle', on))
    _toggle('dry-run 验证模式', pro_cfg.get('dry_run', False),
            lambda on: pet.set_proactive_option('dry_run', on))
    sub.addSeparator()
    open_settings = getattr(pet, 'on_open_modern_settings', None) or getattr(pet, 'on_open_legacy_settings', None)
    if open_settings is not None:
        add_action(sub, '打开设置…', None, open_settings, close_on_trigger=True)


def add_work_briefing_menu(menu: QMenu, pet) -> None:
    """「工作简报」子菜单：WSL 里的 Claude Code 汇总 Jira / PR / Slack / 日程。

    只有装了 WSL、且宿主接了简报服务（overlay 壳）时才出现。"查看 / 现在生成"是命令，
    "工作日自动生成 / 生成时间"是偏好，和会话小鱼的几个选项一样就地放在菜单里。"""
    state_of = getattr(pet, "work_briefing_settings", None)
    settings = state_of() if callable(state_of) and claude_hooks.wsl_exe() else None
    if settings is None:
        return
    from ..work_briefing import TIME_CHOICES

    sub = add_submenu(menu, "工作简报", None)
    add_action(sub, "查看最近一份", None, pet.open_work_briefing, close_on_trigger=True)
    add_action(sub, "现在生成", None, pet.generate_work_briefing, close_on_trigger=True)
    if getattr(getattr(pet, "_shell", None), "work_notes", None) is not None:
        add_action(sub, "工作笔记", None, pet.open_work_notes, close_on_trigger=True)
    sub.addSeparator()
    act = sub.addAction("工作日自动生成")
    act.setCheckable(True)
    act.setChecked(bool(settings["enabled"]))
    act.toggled.connect(lambda on: pet.toggle_work_briefing(on))
    time_menu = add_submenu(sub, "生成时间", None)
    group = QActionGroup(time_menu)
    group.setExclusive(True)
    for value in sorted({*TIME_CHOICES, settings["time"]}):
        choice = time_menu.addAction(value)
        choice.setCheckable(True)
        choice.setChecked(value == settings["time"])
        group.addAction(choice)
        connect_action(choice, lambda value=value: pet.set_work_briefing_time(value))


def add_slack_watch_menu(menu: QMenu, pet) -> None:
    """「Slack 关注」子菜单：电脑在用时每隔几分钟让 WSL 里的 Claude Code 看一眼 Slack。

    和「工作简报」同一个条件才出现（装了 WSL、宿主接了服务）。"""
    state_of = getattr(pet, "slack_watch_settings", None)
    settings = state_of() if callable(state_of) and claude_hooks.wsl_exe() else None
    if settings is None:
        return
    from ..slack_watch import INTERVAL_CHOICES

    sub = add_submenu(menu, "Slack 关注", None)
    add_action(sub, "查看最近一次", None, pet.open_slack_watch, close_on_trigger=True)
    add_action(sub, "现在检查", None, pet.check_slack_now, close_on_trigger=True)
    sub.addSeparator()
    act = sub.addAction("电脑在用时自动检查")
    act.setCheckable(True)
    act.setChecked(bool(settings["enabled"]))
    act.toggled.connect(lambda on: pet.toggle_slack_watch(on))
    interval_menu = add_submenu(sub, "检查间隔", None)
    group = QActionGroup(interval_menu)
    group.setExclusive(True)
    for value in sorted({*INTERVAL_CHOICES, settings["interval_minutes"]}):
        choice = interval_menu.addAction(f"每 {value} 分钟")
        choice.setCheckable(True)
        choice.setChecked(value == settings["interval_minutes"])
        group.addAction(choice)
        connect_action(choice, lambda value=value: pet.set_slack_watch_interval(value))


def add_agent_link_menu(menu: QMenu, pet) -> None:
    """Agent 联动二级菜单（4 个 Agent 独立开关 + 自定义 Agent 三级子菜单 + 气泡提醒选项，失败/拒绝自动回滚勾选）。"""
    sub = add_submenu(menu, "Agent 联动", None)
    agent_cfg = dict(pet.cfg.get('agent_link', {}))
    agents = [
        ('claude', 'Claude Code'),
        ('cursor', 'Cursor'),
        ('opencode', 'OpenCode'),
    ]
    # WSL 里的 Claude Code：只在装了 WSL 的 Windows 上才有这个通道
    if claude_hooks.wsl_exe():
        agents.insert(1, ('claude_wsl', 'Claude Code (WSL)'))   # 紧跟 Claude Code（DSH 项 2026-10-14 下线后首位是 Claude Code）
    for agent_key, agent_label in agents:
        act = sub.addAction(agent_label)
        act.setCheckable(True)
        act.setChecked(bool(agent_cfg.get(agent_key, False)))
        act.toggled.connect(lambda on, k=agent_key, a=act: pet.toggle_agent_link(k, on, a))
    # 每个 Claude Code 会话一只小鱼：只有 overlay 拓扑有这个能力（旧 PetWindow 没有）
    toggle_session_pets = getattr(pet, "toggle_session_pets", None)
    if callable(toggle_session_pets):
        sub.addSeparator()
        act = sub.addAction("每个会话一只小鱼")
        act.setCheckable(True)
        act.setChecked(bool(agent_cfg.get("session_pets", True)))
        act.toggled.connect(lambda on: toggle_session_pets(on))
        set_limit = getattr(pet, "set_session_pets_max", None)
        if callable(set_limit):
            limit_menu = add_submenu(sub, "会话小鱼上限", None)
            current = int(agent_cfg.get("session_pets_max", 6) or 6)
            group = QActionGroup(limit_menu)
            group.setExclusive(True)
            for limit in sorted({3, 6, 9, 12, 16, 24, current}):
                choice = limit_menu.addAction(f"{limit} 只")
                choice.setCheckable(True)
                choice.setChecked(limit == current)
                group.addAction(choice)
                connect_action(choice, lambda limit=limit: set_limit(limit))
        set_card_theme = getattr(pet, "set_session_card_theme", None)
        if callable(set_card_theme):
            from ..session_card_themes import CONFIG_KEY, normalize_theme_id, theme_choices

            theme_menu = add_submenu(sub, "详情卡配色", None)
            current_theme = normalize_theme_id(agent_cfg.get(CONFIG_KEY))
            theme_group = QActionGroup(theme_menu)
            theme_group.setExclusive(True)
            for theme_id, label in theme_choices():
                choice = theme_menu.addAction(label)
                choice.setCheckable(True)
                choice.setChecked(theme_id == current_theme)
                theme_group.addAction(choice)
                connect_action(choice, lambda theme_id=theme_id: set_card_theme(theme_id))
        crown_choices = getattr(pet, "crown_model_choices", None)
        toggle_crown = getattr(pet, "toggle_crown_model", None)
        if callable(crown_choices) and callable(toggle_crown):
            # 测试替身的宿主可能对任何属性都回一个返回 None 的函数：按空清单处理
            choices = crown_choices() or ()
            crown_menu = add_submenu(sub, "桂冠给哪个模型", None)
            for token, label, checked in choices:
                choice = crown_menu.addAction(label)
                choice.setCheckable(True)
                choice.setChecked(bool(checked))
                choice.toggled.connect(lambda on, token=token: toggle_crown(token, on))
    # 灵动岛「最近的对话」：记下每个会话在哪打开的（同样只有 overlay 拓扑有）
    toggle_session_history = getattr(pet, "toggle_session_history", None)
    if callable(toggle_session_history):
        act = sub.addAction("记录最近的对话")
        act.setCheckable(True)
        act.setChecked(bool(agent_cfg.get("session_history", True)))
        act.toggled.connect(lambda on: toggle_session_history(on))
        set_rows = getattr(pet, "set_session_history_rows", None)
        if callable(set_rows):
            rows_menu = add_submenu(sub, "最近的对话显示行数", None)
            current_rows = int(agent_cfg.get("session_history_rows", 10) or 10)
            rows_group = QActionGroup(rows_menu)
            rows_group.setExclusive(True)
            for rows in sorted({5, 8, 10, 12, 15, 20, current_rows}):
                choice = rows_menu.addAction(f"{rows} 行")
                choice.setCheckable(True)
                choice.setChecked(rows == current_rows)
                rows_group.addAction(choice)
                connect_action(choice, lambda rows=rows: set_rows(rows))
    add_work_briefing_menu(sub, pet)
    add_slack_watch_menu(sub, pet)
    # 自定义联动 Agent（config.json 的 agent_link.custom_agents，只读监听）：
    # 收进三级子菜单，避免用户配了多个自定义通道后把联动菜单撑长。
    custom_items = [
        item for item in (agent_cfg.get('custom_agents') or [])
        if str(item.get('key') or '')
    ]
    if custom_items:
        custom_sub = add_submenu(sub, "自定义联动 Agent", None)
        for item in custom_items:
            key = str(item.get('key'))
            act = custom_sub.addAction(str(item.get('name') or key))
            act.setCheckable(True)
            act.setChecked(bool(agent_cfg.get(key, False)))
            act.toggled.connect(lambda on, k=key, a=act: pet.toggle_agent_link(k, on, a))


def build_size_menu(menu: QMenu, pet, *, icons: bool = True) -> QMenu:
    submenu = add_submenu(menu, "大小", "size" if icons else None)
    group = QActionGroup(submenu)
    group.setExclusive(True)
    for scale in catalog.SCALE_STEPS:
        px = int(round(catalog.CANVAS_W * scale))
        action = submenu.addAction(f"{px}px")
        action.setCheckable(True)
        action.setChecked(abs(pet.scale - scale) < 0.02)
        group.addAction(action)
        connect_action(action, lambda scale=scale: pet.change_scale(scale))
    return submenu


def add_drag_physics(menu: QMenu, pet, *, icons: bool = True):
    action = add_action(menu, "拖动物理", "physics" if icons else None)
    action.setCheckable(True)
    action.setChecked(pet.drag_physics)
    action.toggled.connect(lambda enabled, pet=pet: pet.set_drag_physics(enabled))
    return action


def add_return_corner(menu: QMenu, pet, *, icons: bool = True):
    return add_action(menu, "回到右下角", "corner" if icons else None, pet.go_default_corner)


def add_hide_pet(menu: QMenu, pet, *, icons: bool = True):
    # close_on_trigger：隐藏后菜单随之关闭，避免菜单悬空无法找回肥鱼
    return add_action(menu, "隐藏肥鱼", "hide" if icons else None, pet.hide, close_on_trigger=True)


def add_look_screen(menu: QMenu, pet, *, icons: bool = True):
    callback = getattr(pet, "on_look_screen", None)
    if callback is None:
        return None
    return add_action(menu, "看看屏幕", "screen" if icons else None, callback, close_on_trigger=True)



def add_no_move(menu: QMenu, pet, *, icons: bool = True):
    action = add_action(menu, "不移动", "pause" if icons else None)
    action.setCheckable(True)
    action.setChecked(pet.no_move)
    action.toggled.connect(lambda enabled, pet=pet: pet.set_no_move(enabled))
    return action


def add_on_top(menu: QMenu, pet, *, icons: bool = True):
    action = add_action(menu, "窗口置顶", "pin" if icons else None)
    action.setCheckable(True)
    action.setChecked(bool(pet.cfg.get("on_top", True)))
    action.toggled.connect(lambda enabled, pet=pet: pet.set_on_top(enabled))
    return action


def add_autostart(menu: QMenu, pet=None, *, icons: bool = True):
    action = add_action(menu, "开机自启", "autostart" if icons else None)
    action.setCheckable(True)
    action.setChecked(autostart_mod.is_enabled())
    def toggle(enabled: bool) -> None:
        autostart_mod.set_enabled(enabled)
        if pet is not None:
            pet.cfg.set("autostart_wanted", bool(enabled))
            pet.cfg.save()

    action.toggled.connect(toggle)
    return action


def add_spawn_pet(menu: QMenu, pet):
    callback = getattr(pet, "on_spawn_pet", None)
    if callback is None:
        return None
    if str(menu.property("menuStyle") or "") == "modern":
        icon = pet_avatar_menu_icon(menu, pet)
    else:
        icon = QIcon()
    action = menu.addAction(icon, "生小肥鱼")
    action.setProperty("closeOnTrigger", True)
    connect_action(action, callback)
    return action


def add_clear_spawned_pets(menu: QMenu, pet, *, icons: bool = True):
    """右键菜单快捷入口：退出所有小肥鱼（slot-N），设置与数据保留。"""
    callback = getattr(pet, "on_clear_spawned_pets", None)
    if callback is None:
        return None
    return add_action(
        menu,
        "退出子肥鱼",
        "clear" if icons else None,
        callback,
        close_on_trigger=True,
    )


def add_rally_pets(menu: QMenu, pet, *, icons: bool = True):
    """右键菜单：护驾——所有小肥鱼围到主肥鱼身边（只有主肥鱼有这个入口）。"""
    callback = getattr(pet, "on_rally_pets", None)
    if callback is None:
        return None
    return add_action(
        menu,
        "护驾",
        "interaction" if icons else None,
        callback,
        close_on_trigger=True,
    )


def add_golden_spin(menu: QMenu, pet, *, icons: bool = True):
    """右键菜单快捷入口：让肥鱼原地逆时针旋转一圈。"""
    callback = getattr(pet, "trigger_golden_spin", None)
    return add_action(
        menu,
        "黄金回旋",
        "play" if icons else None,
        callback,
        close_on_trigger=True,
    )


def add_edge_probe(menu: QMenu, pet, *, icons: bool = True):
    """右键菜单开关：开启/关闭拖到屏幕边缘后的自动探头。"""
    action = add_action(menu, "边缘探头", "corner" if icons else None)
    action.setCheckable(True)
    action.setChecked(bool(pet.cfg.get("edge_probe_enabled", False)))
    action.toggled.connect(
        lambda enabled, pet=pet: pet.set_edge_probe_enabled(enabled)
    )
    return action



def _music_controller(pet):
    """取歌词控制器。**不**在这里创建——仅打开菜单不该装一套定时器。

    必须校验类型而不是只判断 None：宿主可能用 ``__getattr__`` 兜底返回任意
    对象（测试替身就这么干），那样会把一个无关对象当成控制器。
    """
    from ..music_lyric_controller import MusicLyricController

    controller = getattr(pet, "_music_lyric", None)
    return controller if isinstance(controller, MusicLyricController) else None


def _skip_track(pet, direction: str) -> bool:
    controller = _music_controller(pet)
    if controller is None:
        return False
    return controller.skip_track(direction)


def music_mode_active(pet) -> bool:
    """音乐模式是否在跑（含"临时退出"状态），供菜单勾选态与可用性判断。"""
    controller = _music_controller(pet)
    if controller is not None:
        return controller.music_mode_active()
    return bool(pet.cfg.get("music_lyric_enabled", False))


def set_music_mode(pet, on: bool) -> None:
    """临时进入/退出音乐模式（仅本次运行，不写设置）。"""
    controller = _music_controller(pet)
    if controller is None:
        installer = getattr(pet, "install_music_lyric", None)
        if callable(installer):
            controller = installer()
    enable = getattr(controller, "set_music_mode_enabled", None)
    if callable(enable):
        enable(on)


def add_vscode_workspaces_menu(menu: QMenu, pet, *, icons: bool = True):
    """「VS Code 工作区」子菜单：开着的（带 ●）、最近用过的、用户目录里的；点一条切过去或打开。

    宿主没有这两个回调（旧 PetWindow）就不出这一项。条目在菜单弹出时现算
    （``pet.vscode_workspace_entries``，读几个小文件，十几毫秒）。"""
    entries_of = getattr(pet, "vscode_workspace_entries", None)
    opener = getattr(pet, "open_vscode_workspace", None)
    if not callable(entries_of) or not callable(opener):
        return None
    sub = add_submenu(menu, "VS Code 工作区", "application" if icons else None)
    entries = list(entries_of() or [])
    if not entries:
        hint = sub.addAction("还没有开过的工作区；可在设置里指定工作区文件目录")
        hint.setEnabled(False)
        return sub
    from .icons import badged_menu_icon, vector_menu_icon

    for entry in entries:
        if icons:
            # 图标说明在哪（Ubuntu = WSL，Windows = 本机）；开着的在图标右下角带一个绿点
            label = entry.label
        else:
            label = f"{'● ' if entry.open else ''}{entry.label}{' [WSL]' if entry.wsl else ''}"
        action = add_action(sub, label, None, lambda entry=entry: opener(entry), close_on_trigger=True)
        if icons:
            glyph = "ubuntu" if entry.wsl else "windows"
            action.setIcon(badged_menu_icon(sub, glyph) if entry.open else vector_menu_icon(sub, glyph))
        action.setToolTip(entry.target + ("（开着）" if entry.open else ""))
    return sub


def _run_off_main(callable_) -> None:
    """把播放器控制丢到后台线程执行。

    now_playing 的控制接口内部走 asyncio.run() 调 WinRT，实测会在主线程
    永久阻塞（窗口未响应）。菜单回调都在主线程，必须挪走。
    """
    threading.Thread(target=callable_, name="music-menu", daemon=True).start()


def add_music_pause(menu: QMenu, pet, *, icons: bool = True):
    """音乐子菜单：暂停 / 播放。"""
    from .. import now_playing

    return add_action(
        menu, "让人家歇一会儿嘛（暂停 / 播放）", "pause" if icons else None,
        lambda: _run_off_main(now_playing.toggle_play_pause), close_on_trigger=True,
    )


def add_music_next(menu: QMenu, pet, *, icons: bool = True):
    """音乐子菜单：切歌。"""
    return add_action(
        menu, "给主人换一首（切歌）", "play" if icons else None,
        lambda: _run_off_main(lambda: _skip_track(pet, "next")), close_on_trigger=True,
    )


def add_music_prev(menu: QMenu, pet, *, icons: bool = True):
    """音乐子菜单：切到上一首。"""
    return add_action(
        menu, "人家想再听刚才那首（上一首）", "play" if icons else None,
        lambda: _run_off_main(lambda: _skip_track(pet, "previous")), close_on_trigger=True,
    )


def add_music_quit(menu: QMenu, pet, *, icons: bool = True):
    """音乐子菜单开关：临时退出音乐模式（勾选=已退出）。"""
    action = add_action(menu, "人家今天不唱了（退出音乐模式）", "stop" if icons else None)
    action.setCheckable(True)
    action.setChecked(not music_mode_active(pet))
    action.toggled.connect(lambda off: set_music_mode(pet, not off))
    return action


def _align_lyric(pet, kind: str) -> bool:
    """执行一次歌词对齐；返回是否真的动作了。

    **纯内存操作，必须留在 GUI 线程**（其余音乐菜单项走 ``_run_off_main`` 是因为
    它们要调 WinRT）。这里只改 LyricTracker 的本地时钟基准，微秒级。
    """
    controller = _music_controller(pet)
    if controller is None:
        return False
    if kind == "start":
        return controller.resync_to_start()
    if kind == "prev":
        return controller.resync_to_line(-1)
    if kind == "next":
        return controller.resync_to_line(1)
    if kind == "back5":
        return controller.nudge(-5.0)
    if kind == "fwd5":
        return controller.nudge(5.0)
    return False


def add_music_lyric_align(menu: QMenu, pet, *, icons: bool = True):
    """「歌词对齐」子菜单：纠正快进 / 中途开始播放造成的歌词错位。

    为什么是"一个 id 挂子菜单"而不是五个平级项：与 ``add_harness`` 同一个理由——
    菜单模板与用户自己编排过的布局里只会出现 ``music_lyric_align`` 这一个 id。

    为什么用「上一句 / 下一句」做主手柄：用户听到的是"现在唱这句"，而不是
    "现在第几秒"，按行步进比按秒微调快得多；±5 秒留给最后一点偏差。

    实测依据（2026-09-21）：网易云音乐完全不上报播放进度，歌词只能按本地时钟
    估算，快进或中途开始播放后必然错位，且没有任何自动信号可利用——所以给用户
    一个一次点击就能对准的入口，是这个功能唯一诚实的做法。
    """
    icon = "play" if icons else None
    submenu = add_submenu(menu, "歌词对齐", icon)
    add_action(submenu, "回到开头（现在这句算开头）", icon,
               lambda: _align_lyric(pet, "start"), close_on_trigger=True)
    add_action(submenu, "上一句", icon,
               lambda: _align_lyric(pet, "prev"), close_on_trigger=True)
    add_action(submenu, "下一句", icon,
               lambda: _align_lyric(pet, "next"), close_on_trigger=True)
    add_action(submenu, "后退 5 秒", icon,
               lambda: _align_lyric(pet, "back5"), close_on_trigger=True)
    add_action(submenu, "前进 5 秒", icon,
               lambda: _align_lyric(pet, "fwd5"), close_on_trigger=True)
    return submenu


#: 「YouTube Music」打开的地址：首页，由默认浏览器打开（不带播放参数，不自动开始播放）
YOUTUBE_MUSIC_URL = "https://music.youtube.com/"


def add_youtube_music(menu: QMenu, pet, *, icons: bool = True):
    """「YouTube Music」：用默认浏览器打开 YouTube Music 首页。

    2026-10-15 取代「打开网易云 / QQ 音乐给主人放歌」：网页版就够，不找程序、不扫盘。
    放歌之后的歌词气泡与唱歌联动照旧走系统媒体会话（需打开设置里的「浏览器媒体会话
    参与歌词」）。"""
    del pet
    return add_action(
        menu, "YouTube Music", "play" if icons else None,
        lambda: QDesktopServices.openUrl(QUrl(YOUTUBE_MUSIC_URL)), close_on_trigger=True,
    )


def _tell(pet, text: str) -> None:
    """启动失败时冒一句（壳的门面与 PetWindow 都有 ``show_bubble``；没有就只写日志）。"""
    show = getattr(pet, "show_bubble", None)
    if callable(show):
        show(text)


def add_claude_desktop(menu: QMenu, pet, *, icons: bool = True):
    """「Claude Desktop」：拉起本机的 Claude 桌面程序（商店版或老式安装器）；没装的话置灰。"""
    target = claude_launchers.claude_desktop_target()

    def launch() -> None:
        if not claude_launchers.launch_claude_desktop(target):
            _tell(pet, "Claude Desktop 没能拉起来…")

    action = add_action(menu, "Claude Desktop", "sparkle" if icons else None, launch, close_on_trigger=True)
    if not target:
        action.setEnabled(False)
        action.setToolTip("没找到 Claude Desktop")
    return action


def add_wsl_claude_code(menu: QMenu, pet, *, icons: bool = True):
    """「Claude Code（WSL）」：在默认发行版的 ``~/workspace``（已信任过的目录）开一个终端、起一个新的 claude 会话；没有 WSL 置灰。"""
    argv = claude_launchers.wsl_claude_argv()

    def launch() -> None:
        if not claude_launchers.launch_wsl_claude(list(argv or [])):
            _tell(pet, "WSL 里的 Claude Code 没能拉起来…")

    action = add_action(menu, "Claude Code（WSL）", "ubuntu" if icons else None, launch, close_on_trigger=True)
    if argv is None:
        action.setEnabled(False)
        action.setToolTip("没找到 WSL")
    return action


def add_agent_cost(menu: QMenu, pet, *, icons: bool = True):
    """右键菜单开关：本轮结束时显示消费金额。

    与设置页开关同一份配置（``agent_cost_enabled``），两边实时联动。
    """
    action = add_action(menu, "显示本轮消费", "balance" if icons else None)
    action.setCheckable(True)
    action.setChecked(bool(pet.cfg.get("agent_cost_enabled", False)))

    def _on_toggled(on: bool) -> None:
        pet.cfg.set("agent_cost_enabled", bool(on))
        pet.cfg.save()
        # 让窗口按新配置同步控制器（与设置页走同一条刷新路径）。
        for name in ("refresh_pet_settings", "sync_optional_services"):
            fn = getattr(pet, name, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass

    action.toggled.connect(_on_toggled)
    return action



def add_template_switch(menu: QMenu, pet, label: str, target: str, *, icons: bool = True):
    def switch_and_reopen() -> None:
        pet.set_context_menu_template(target)
        reopen = getattr(pet, "reopen_context_menu", None)
        if callable(reopen):
            reopen(menu)

    return add_action(menu, label, "template" if icons else None, switch_and_reopen)


def add_quit(menu: QMenu, pet, *, icons: bool = True):
    return add_action(menu, "退出", "exit" if icons else None, pet.request_quit, close_on_trigger=True)
