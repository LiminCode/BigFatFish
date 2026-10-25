# -*- coding: utf-8 -*-
"""Modern-inspired sidebar settings panel used by the modern context menu.

拆分后的主对话框模块：ModernSettingsDialog 及对话框装配/配置写回逻辑留守本文件。
控件库 / 菜单布局编辑器 / AI 设置页 / 主题 QSS 已按结构线拆至
settings_widgets / settings_menu_layout_editor / chat/ai_settings_page / settings_theme_qss。
本文件保留这些符号的 re-export，供 tests 与 pet/ 既有调用向后兼容。
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

import shiboken6


from PySide6.QtCore import QEvent, QFileInfo, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QClipboard,
    QFontDatabase,
    QIcon,
    QImageReader,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QBoxLayout,
    QDialog,
    QColorDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFileIconProvider,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QLayout,
    QMessageBox,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import autostart as autostart_mod
from . import catalog
from .click_sound import warm_click_sound_effects
from .config import (
    DEFAULT_CONTEXT_MENU_APPEARANCE,
    DEFAULT_MENU_EASTER_EGG,
    DEFAULT_QUICK_LAUNCH_APPS,
    DEFAULT_SELF_TALK_BUBBLE_STYLE,
    DEFAULT_SELF_TALK_DURATION_SECONDS,
    DEFAULT_SELF_TALK_MAX_INTERVAL,
    DEFAULT_SELF_TALK_MIN_INTERVAL,
    DEFAULT_SELF_TALK_TEXTS,
    _float_or_default,
)
from .context_menus.icons import (
    CUSTOM_ICON_SUFFIXES,
    custom_icon_file_error,
    vector_widget_icon,
)
from .context_menus.quick_launch import fitted_application_icon
from .context_menus.registry import CUSTOM_ICON_CHOICES, MENU_ACTIONS
from .fun_image_popup import oijingjing_image_path, resolve_fun_asset, store_fun_asset
from .menu_layout import (
    load_default_menu_layout,
    materialize_implicit_separators,
    merge_default_menu_actions,
    resolve_menu_layout,
)
from .speech_bubble import BUBBLE_STYLE_PRESETS


def _chat_feature_available() -> bool:
    """本构建是否带聊天模块（纯肥鱼版打包时排除 pet.chat，与 app.py
    ChatService 导入守卫同一判定口径）。"""
    try:
        from .chat.service import ChatService  # noqa: F401
    except ImportError as exc:
        if str(getattr(exc, "name", "") or "").startswith("pet.chat"):
            return False
        raise
    return True

from .settings_widgets import (
    _system_font_families,
    BROWSER_CONTROL_SPEC,
    SETTINGS_DOMAIN_NAV,
    domain_label,
    BROWSER_CONTROL_STYLESHEET,
    _widget_dark,
    TiltButton,
    TiltItemDelegate,
    ToggleSwitch,
    IMAGE_NAME_FILTER,
    AUDIO_NAME_FILTER,
    ClickSoundPackPicker,
    MasonryLayout,
    MasonryImageCard,
    MasonryFlow,
    ImagePreviewDrawer,
    ResourcePathPicker,
    ColorSwatchButton,
    ColorPicker,
    _draw_chevron,
    SETTINGS_POPUP_OBJECT_NAME,
    SETTINGS_POPUP_STYLESHEET,
    _DARK_POPUP_OVERRIDE,
    settings_popup_stylesheet,
    configure_settings_action_popup,
    SettingsPopupAction,
    SettingsPopupMenu,
    SettingsMenuButton,
    ModernSelect,
    BrowserSpinBox,
    BrowserDoubleSpinBox,
    CollapsibleGroup,
    SettingRow,
    ResponsiveActionRow,
    ResponsiveToggleActionRow,
    SettingsCard,
    SettingsDisclosureHeader,
    SettingsSection,
    SettingsTabContainer,
    _SettingsPageShell,
    _line_edit,
    QuickLaunchItemRow,
    QuickLaunchEditor,
    _system_dark,
)
from .settings_theme_qss import _settings_stylesheet
from .settings_menu_layout_editor import MenuLayoutEditor
from .persona_template import (
    CONDITIONAL_PARAMETERS,
    PARAMETERS,
)
from . import settings_file_interpret
from . import settings_interaction
from . import settings_music
from . import settings_pet_controls
from . import settings_save
from . import settings_language
from . import settings_tray
from . import settings_island_icon
from . import (
    settings_help, settings_notifications, settings_personal, settings_slack_watch, settings_vscode, settings_work_briefing,
    settings_work_notes,
)
from .i18n import t
from .settings_dialogue_text import DIALOGUE_LABELS, DIALOGUE_PARAMS, dialogue_label, dialogue_param



# 与 persona_template.PARAMETERS 保持同一真相源：调用点注入什么，这里就宣称什么。
DIALOGUE_KEY_PARAMS = dict(PARAMETERS)


def dialogue_params_hint(key: str) -> str:
    """「可用参数」提示文案：区分保证注入与条件注入（仅上游记录提供时可用）。"""
    params = DIALOGUE_KEY_PARAMS.get(key, ())
    if not params:
        return ""
    text = "、".join("{" + item + "}（" + dialogue_param(item) + "）" for item in params)
    conditional = [item for item in params if item in CONDITIONAL_PARAMETERS.get(key, ())]
    if conditional:
        text += t("settings.dlg.these") + "、".join("{" + item + "}" for item in conditional) + t("settings.dlg.are_only_available_when_upstream")
    return text


class ModernSettingsDialog(QDialog):
    """Settings window matching Modern's sidebar and rounded-card hierarchy."""

    saved = Signal()    # 「保存」写盘成功（窗口还开着）：进程内宿主据此立刻应用

    def __init__(self, config, parent=None, *, include_ai: bool = True,
                 standalone: bool = False, initial_page: str | None = None):
        super().__init__(parent)
        self.config = config
        self.include_ai = bool(include_ai)
        # standalone=True：本对话框跑在独立设置进程（python -m pet --settings）里，
        # 没有肥鱼窗口/AppShell 可依附。只影响下面几处显式分支，默认 False 时
        # 全部行为与改动前逐位一致。
        self.standalone = bool(standalone)
        self.initial_page = str(initial_page or "").strip()
        self.ai_page = None
        self.setProperty("modernStyle", True)
        self.setProperty("menuStyle", "modern")
        self.setWindowTitle(t("settings.dlg.fish_settings"))
        self.resize(800, 560)
        self.setMinimumSize(720, 500)
        self._positioned_away = False
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
        font.setPixelSize(13)
        self.setFont(font)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        sidebar_pane = QFrame(self)
        sidebar_pane.setObjectName("sidebarPane")
        sidebar_pane.setFixedWidth(200)
        sidebar_layout = QVBoxLayout(sidebar_pane)
        sidebar_layout.setContentsMargins(12, 16, 12, 12)
        sidebar_layout.setSpacing(9)
        self.save_exit_button = TiltButton(t("settings.dlg.save_exit"), sidebar_pane)
        self.save_exit_button.setObjectName("saveAndExit")
        self.save_exit_button.setIcon(vector_widget_icon(self.save_exit_button, "back", 16))
        self.save_exit_button.clicked.connect(self._save)
        self.save_exit_button.setAutoDefault(False)
        self.save_exit_button.setDefault(False)
        sidebar_layout.addWidget(self.save_exit_button)
        # 「保存」：写盘不关窗，改动立刻生效（Ctrl+S 同义）；实现见 settings_save
        settings_save.install_save_button(self, sidebar_pane, sidebar_layout)
        self.search_edit = QLineEdit(sidebar_pane)
        self.search_edit.setObjectName("settingsSearch")
        self.search_edit.setPlaceholderText(t("settings.dlg.search_settings"))
        self.search_edit.addAction(
            vector_widget_icon(self, "search", 16),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.search_edit.installEventFilter(self)
        sidebar_layout.addWidget(self.search_edit)
        self.search_status = QLabel("", sidebar_pane)
        self.search_status.setObjectName("searchStatus")
        self.search_status.setWordWrap(True)
        self.search_status.hide()
        sidebar_layout.addWidget(self.search_status)
        self.sidebar = QListWidget(sidebar_pane)
        self.sidebar.setObjectName("settingsSidebar")
        self.sidebar.setIconSize(QSize(18, 18))
        self.sidebar.setSpacing(2)
        TiltItemDelegate.install(self.sidebar)      # Metro：被悬停的侧栏项像磁贴一样朝光标倾斜
        sidebar_layout.addWidget(self.sidebar, 1)
        # 侧栏左下角的版本号 2026-10-14 去掉：从源码运行、不再发版，没有「版本」可言

        self.pages = QStackedWidget(self)
        body.addWidget(sidebar_pane)
        body.addWidget(self.pages, 1)
        root.addLayout(body, 1)

        self._build_pet_controls()
        # 「文件识别」域控件在本模块构建（行数预算原因），见 settings_file_interpret。
        self._build_file_interpret_controls()
        # 「随肥鱼启动 dsh 服务」「自启目标」2026-10-14 从设置页下线（DeepSeek Harness 不再暴露入口；配置键保留）

        # 灵动岛控件构建保留在对话框本体，便于上游直接修改后上传。
        island_cfg = self.config.get("dynamic_island", {})
        if not isinstance(island_cfg, dict):
            island_cfg = {}
        self.island_enabled_check = ToggleSwitch(self)
        self.island_enabled_check.setChecked(bool(island_cfg.get("enabled", False)))
        self.island_icon_check = ToggleSwitch(self)
        self.island_icon_check.setChecked(bool(island_cfg.get("show_icon", True)))
        self.island_name_check = ToggleSwitch(self)
        self.island_name_check.setChecked(bool(island_cfg.get("show_name", True)))
        self.island_info_check = ToggleSwitch(self)
        self.island_info_check.setChecked(bool(island_cfg.get("show_info", True)))
        self.island_status_check = ToggleSwitch(self)
        self.island_status_check.setChecked(bool(island_cfg.get("show_status", True)))
        self.island_info_mode_select = ModernSelect(self, width=160)
        for label, value in (
            (t("settings.dlg.current_time"), "time"),
            (t("settings.dlg.today_usage"), "usage_today"),
        ):
            self.island_info_mode_select.addItem(label, value)
        self.island_info_mode_select.setCurrentData(str(island_cfg.get("info_mode") or "time"))
        self.island_card_source_select = settings_pet_controls.build_island_card_source_select(self, island_cfg)
        self.island_style_select = ModernSelect(self, width=160)
        for label, value in (
            (t("settings.dlg.black"), "dark"),
            (t("settings.dlg.white"), "light"),
            (t("settings.dlg.glass"), "glass"),
            (t("settings.dlg.metro"), "metro"),
        ):
            self.island_style_select.addItem(label, value)
        self.island_style_select.setCurrentData(str(island_cfg.get("style") or "dark"))
        self.island_opacity_spin = BrowserDoubleSpinBox(self)
        self.island_opacity_spin.setRange(0.4, 1.0)
        self.island_opacity_spin.setSingleStep(0.05)
        self.island_opacity_spin.setDecimals(2)
        try:
            _island_opacity = float(island_cfg.get("opacity", 1.0))
        except (TypeError, ValueError):
            _island_opacity = 1.0
        self.island_opacity_spin.setValue(max(0.4, min(1.0, _island_opacity)))
        self.island_accent_select = ModernSelect(self, width=160)
        for label, value in (
            (t("settings.dlg.ocean_blue"), "blue"),
            (t("settings.dlg.grass_green"), "green"),
            (t("settings.dlg.grape_purple"), "purple"),
            (t("settings.dlg.sakura_pink"), "pink"),
            (t("settings.dlg.sunset_orange"), "orange"),
        ):
            self.island_accent_select.addItem(label, value)
        self.island_accent_select.setCurrentData(str(island_cfg.get("accent") or "blue"))
        # 图标：点方块直接选一张自己的图（2026-10-20 起取代原来的头像 / emoji 下拉框）
        island_icon_row = settings_island_icon.island_icon_row(self, island_cfg)
        self.island_click_action_select = ModernSelect(self, width=160)
        for label, value in (
            (t("settings.dlg.expand_quick_card"), "expand"),
            (t("settings.dlg.show_hide_fish"), "toggle_pet"),
        ):
            self.island_click_action_select.addItem(label, value)
        self.island_click_action_select.setCurrentData(str(island_cfg.get("click_action") or "expand"))
        self.island_event_effects_check = ToggleSwitch(self)
        self.island_event_effects_check.setChecked(bool(island_cfg.get("event_effects", True)))
        self.island_hidden_chat_check = ToggleSwitch(self)
        self.island_hidden_chat_check.setChecked(bool(island_cfg.get("hidden_chat", True)))
        self.island_edge_dock_check = ToggleSwitch(self)
        self.island_edge_dock_check.setChecked(bool(island_cfg.get("edge_dock", True)))
        self.island_collision_check = ToggleSwitch(self)
        self.island_collision_check.setChecked(bool(island_cfg.get("collision_enabled", True)))

        if include_ai:
            # 延迟 import：no-chat 打包变体 excludes=['pet.chat']，顶层导入会在
            # 产物运行时抛 ModuleNotFoundError，导致设置界面整体打不开。
            from .chat.ai_settings_page import _AiSettingsPage

            self.ai_page = _AiSettingsPage(config, self)

        general_content = QWidget()
        general_layout = QVBoxLayout(general_content)
        general_layout.setContentsMargins(0, 0, 0, 0)
        general_layout.setSpacing(18)
        autostart_desc = t("settings.dlg.start_fish_automatically_when_you") if not self.config.instance_id else t("settings.dlg.start_fish_automatically_when_you_2")
        launch_rows = [
            SettingRow("autostart", t("settings.dlg.start_at_sign"), autostart_desc, self.autostart_check),
        ]
        if sys.platform == "darwin":
            launch_rows.append(
                SettingRow(
                    "dock_icon",
                    t("settings.dlg.show_dock_icon"),
                    t("settings.dlg.show_fish_app_macos_dock"),
                    self.dock_icon_check,
                )
            )
        general_layout.addWidget(SettingsSection(t("settings.dlg.language"), settings_language.language_rows(self), general_content))
        general_layout.addWidget(SettingsSection(t("settings.dlg.startup"), launch_rows, general_content))
        window_rows = [
            SettingRow("on_top", t("settings.dlg.always_top"), t("settings.dlg.keep_fish_above_other_windows"), self.on_top_check),
        ]
        if sys.platform == "win32":
            window_rows.extend(
                [
                    SettingRow("auto_hide_fullscreen", t("settings.dlg.hide_full_screen"), t("settings.dlg.hide_fish_automatically_while_full"), self.auto_hide_fullscreen_check),
                    SettingRow(
                        "cursor_hidden_passthrough",
                        t("settings.dlg.click_through_when_cursor_hidden"),
                        t("settings.dlg.when_windows_hides_cursor_fish"),
                        self.cursor_hidden_passthrough_check,
                    ),
                    SettingRow("stream_capture", t("settings.dlg.stream_capture_compatibility"), settings_pet_controls.stream_capture_hint(), self.stream_capture_check),
                ]
            )
        window_rows.extend(settings_tray.tray_icon_rows(self))
        general_layout.addWidget(SettingsSection(t("settings.dlg.window_system"), window_rows, general_content))
        # 拓扑收口：「单进程多开」实验开关已从设置页移除，4.4b 起配置键
        # `experimental_single_process_spawn` 本身也随多进程多宠退役层删除
        # （进程内多窗是唯一多宠形态，不再是可切换的实验开关）。
        # 「余额与服务状态」（DeepSeek 余额刷新 / 峰谷文案 / 峰谷颜色）2026-10-14 从设置页下线：用不到 DeepSeek 了；
        # 配置键与余额代码保留（见 docs/PR-REPORT-SETTINGS-METRO-2026-10-14.md 第二轮）。
        general_layout.addStretch(1)
        self._add_page(t("settings.dlg.general"), "settings", self._page_shell(t("settings.dlg.general"), general_content))

        island_content = QWidget()
        island_layout = QVBoxLayout(island_content)
        island_layout.setContentsMargins(0, 0, 0, 0)
        island_layout.setSpacing(18)
        island_layout.addWidget(
            SettingsSection(
                t("settings.dlg.dynamic_island"),
                [
                    SettingRow("dynamic_island_enabled", t("settings.dlg.enable_dynamic_island"), t("settings.dlg.show_separate_capsule_window_stays"), self.island_enabled_check),
                    SettingRow("dynamic_island_icon", t("settings.dlg.show_icon"), t("settings.dlg.show_character_icon_left_capsule"), self.island_icon_check),
                    SettingRow("dynamic_island_name", t("settings.dlg.show_name"), t("settings.dlg.show_current_character_name"), self.island_name_check),
                    SettingRow("dynamic_island_info", t("settings.dlg.show_info_slot"), t("settings.dlg.show_current_time_today_claude"), self.island_info_check),
                    SettingRow("dynamic_island_status", t("settings.dlg.show_status_lights"), t("settings.dlg.show_claude_code_session_count"), self.island_status_check),
                    SettingRow("dynamic_island_info_mode", t("settings.dlg.info_slot_content"), t("settings.dlg.current_time_today_usage_tokens"), self.island_info_mode_select),
                    SettingRow("dynamic_island_card_source", t("settings.dlg.card_content"), t("settings.dlg.what_expanded_card_shows_auto"), self.island_card_source_select),
                    SettingRow(
                        "dynamic_island_style",
                        t("settings.dlg.background_style"),
                        t("settings.dlg.black_white_apple_style_glass"),
                        self.island_style_select,
                    ),
                    SettingRow("dynamic_island_opacity", t("settings.dlg.background_opacity"), t("settings.dlg.lower_more_transparent_0_4"), self.island_opacity_spin),
                    SettingRow("dynamic_island_accent", t("settings.dlg.accent_color"), t("settings.dlg.accent_shared_by_icon_ring"), self.island_accent_select),
                    island_icon_row,
                    SettingRow(
                        "dynamic_island_click_action",
                        t("settings.dlg.click_action"),
                        t("settings.dlg.clicking_capsule_either_expands_quick"),
                        self.island_click_action_select,
                    ),
                    *([SettingRow(
                        "dynamic_island_hidden_chat",
                        t("settings.dlg.alert_island_while_hidden"),
                        t("settings.dlg.while_fish_hidden_agent_link"),
                        self.island_hidden_chat_check,
                    )] if _chat_feature_available() else []),
                    # 纯肥鱼版（无 pet.chat 打包变体）不展示该开关：开了也没有
                    # 气泡可弹——运行时岛侧已由 chat_available 回退展开卡片
                    SettingRow(
                        "dynamic_island_event_effects",
                        t("settings.dlg.event_animation"),
                        t("settings.dlg.jelly_bounce_when_ai_reply"),
                        self.island_event_effects_check,
                    ),
                    SettingRow(
                        "dynamic_island_edge_dock",
                        t("settings.dlg.half_hide_at_edge"),
                        t("settings.dlg.drag_any_screen_edge_top"),
                        self.island_edge_dock_check,
                    ),
                    SettingRow(
                        "dynamic_island_collision",
                        t("settings.dlg.jelly_wall_collides"),
                        t("settings.dlg.island_becomes_static_collider_fish"),
                        self.island_collision_check,
                    ),
                ],
                island_content,
            )
        )
        island_layout.addStretch(1)
        self._add_page(t("settings.dlg.dynamic_island"), "island", self._page_shell(t("settings.dlg.dynamic_island"), island_content))

        behavior_content = QWidget()
        behavior_layout = QVBoxLayout(behavior_content)
        behavior_layout.setContentsMargins(0, 0, 0, 0)
        behavior_layout.setSpacing(16)
        behavior_layout.addWidget(
            SettingsSection(
                t("settings.dlg.animation"),
                [
                    SettingRow("playback_speed", t("settings.dlg.playback_speed"), t("settings.dlg.how_fast_all_fish_animations"), self.speed_select),
                    SettingRow("animation_gap", t("settings.dlg.pause_between_actions"), t("settings.dlg.rest_time_between_non_idle"), self.gap_spin),
                    SettingRow(
                        "idle_low_fps",
                        t("settings.dlg.power_saving"),
                        settings_pet_controls.idle_low_fps_hint(),
                        self.idle_low_fps_check,
                    ),
                    SettingRow("no_move", t("settings.dlg.stay_put"), t("settings.dlg.pause_fish_automatic_wandering_desktop"), self.no_move_check),
                    # 鼠标穿透行归「互动 · 输入」（settings_interaction 构建）。
                ],
                behavior_content,
            )
        )
        behavior_layout.addWidget(
            SettingsSection(
                t("settings.dlg.music"),
                [
                    SettingRow("music_sing", t("settings.dlg.sing_along_music"), t("settings.dlg.play_singing_animation_automatically_whe"), self.music_sing_check),
                    SettingRow("music_lyric", t("settings.dlg.show_lyrics"), t("settings.dlg.show_current_song_lyrics_bubble"), self.music_lyric_check),
                    SettingRow("music_lyric_lead", t("settings.dlg.lyric_lead_time"), t("settings.dlg.shift_lyrics_relative_audio_positive"), self.music_lyric_lead_spin),
                ] + settings_music.browser_media_rows(self),
                behavior_content,
            )
        )
        behavior_layout.addWidget(
            SettingsSection(
                t("settings.dlg.drag_fling"),
                [
                    SettingRow("drag_physics", t("settings.dlg.drag_physics"), t("settings.dlg.enable_drag_inertia_gravity_edge"), self.drag_physics_check),
                    SettingRow("throw_strength", t("settings.dlg.fling_strength"), t("settings.dlg.caps_top_speed_when_fish"), self.throw_strength_select),
                    SettingRow("slingshot_enabled", t("settings.dlg.slingshot"), t("settings.dlg.while_dragging_fish_right_click"), self.slingshot_check),
                    SettingRow("lock_position", t("settings.dlg.lock_position"), t("settings.dlg.fish_stays_where_can_t"), self.lock_position_check),
                    SettingRow("shift_drag", t("settings.dlg.shift_left_drag"), t("settings.dlg.when_you_have_hold_shift"), self.shift_drag_check),
                ],
                behavior_content,
            )
        )
        behavior_layout.addWidget(
            SettingsSection(
                t("settings.dlg.peek_from_edge"),
                [
                    SettingRow(
                        "edge_probe", t("settings.dlg.peek_from_edge"), t("settings.dlg.dragged_left_right_screen_edge"), self.edge_probe_check
                    ),
                ],
                behavior_content,
            )
        )
        behavior_layout.addWidget(
            SettingsSection(
                t("settings.dlg.spawn_little_fish"),
                [
                    SettingRow(
                        "spawn_inherit_size",
                        t("settings.dlg.little_fish_inherit_size"),
                        t("settings.dlg.when_spawned_little_fish_match"),
                        self.spawn_inherit_size_check,
                    ),
                    SettingRow("spawn_smaller_than_main", t("settings.dlg.one_size_smaller_than_main"), t("settings.dlg.when_inheriting_size_new_little"), self.spawn_smaller_check),
                    SettingRow("spawn_scale", t("settings.dlg.little_fish_size"), t("settings.dlg.desktop_size_new_little_fish"), self.spawn_scale_combo, stacked=True),
                    SettingRow(
                        "spawn_inherit_dynamic_island",
                        t("settings.dlg.little_fish_inherit_dynamic_island"),
                        t("settings.dlg.off_by_default_new_little"),
                        self.spawn_inherit_dynamic_island_check,
                    ),
                    SettingRow(
                        "clear_spawned_pets", t("settings.dlg.close_all_little_fish"), t("settings.dlg.close_every_spawned_little_fish"), self.clear_spawned_pets_btn
                    ),
                ],
                behavior_content,
            )
        )
        behavior_layout.addWidget(
            SettingsSection(
                t("settings.dlg.multi_fish_collisions"),
                [
                    SettingRow(
                        "collision_enabled",
                        t("settings.dlg.collisions"),
                        t("settings.dlg.fish_collide_each_other_physically"),
                        self.collision_enabled_check,
                    ),
                    SettingRow("collision_restitution", t("settings.dlg.elasticity"), t("settings.dlg.how_much_energy_bounce_keeps"), self.collision_restitution_spin),
                    SettingRow("collision_friction", t("settings.dlg.friction"), t("settings.dlg.tangential_friction_glancing_hits_0"), self.collision_friction_spin),
                    SettingRow("collision_mass_scale", t("settings.dlg.mass_multiplier"), t("settings.dlg.weighting_fish_base_mass_0"), self.collision_mass_scale_spin),
                    SettingRow("collision_impulse_cap", t("settings.dlg.impulse_cap"), t("settings.dlg.most_impulse_single_collision_can"), self.collision_impulse_cap_spin),
                    SettingRow("collision_sound_enabled", t("settings.dlg.collision_sound"), t("settings.dlg.play_sound_collisions"), self.collision_sound_check),
                    SettingRow("collision_sound_volume", t("settings.dlg.collision_volume"), t("settings.dlg.volume_collision_sound"), self.collision_sound_volume_spin),
                ],
                behavior_content,
            )
        )
        self.collision_policy_note = QLabel(t("settings.dlg.collision_parameters_come_from_coordinat"))
        self.collision_policy_note.setObjectName("settingHint")
        self.collision_policy_note.setWordWrap(True)
        self.collision_policy_note.setContentsMargins(14, 0, 14, 0)
        behavior_layout.addWidget(self.collision_policy_note)
        # 「点击反馈」与「自言自语」两组归「互动」域（settings_interaction 构建，
        # 行数预算原因；组名与顺序的既有契约见 tests/test_menu_layout.py）。
        # Agent 联动：音效设置
        agent_sound_rows = [
            SettingRow("agent_sound_enabled", t("settings.dlg.agent_sound_effects"), t("settings.dlg.play_sound_when_agent_starts"), self.agent_sound_check),
            SettingRow("agent_sound_start", t("settings.dlg.start_sound"), t("settings.dlg.played_when_agent_starts_working"), self.agent_sound_start_widget, stacked=True),
            SettingRow("agent_sound_done", t("settings.dlg.done_sound"), t("settings.dlg.played_when_agent_finishes_task"), self.agent_sound_done_widget, stacked=True),
            SettingRow("agent_sound_error", t("settings.dlg.error_sound"), t("settings.dlg.played_when_agent_runs_into"), self.agent_sound_error_widget, stacked=True),
            SettingRow("agent_sound_volume", t("settings.dlg.sound_volume"), t("settings.dlg.volume_agent_sounds"), self.agent_sound_volume_spin),
            SettingRow("agent_sound_cooldown", t("settings.dlg.cooldown"), t("settings.dlg.keeps_sounds_from_firing_too"), self.agent_sound_cooldown_spin),
        ]
        behavior_layout.addWidget(SettingsSection(t("settings.dlg.agent_link_sounds"), agent_sound_rows, behavior_content))
        labels = {key: dialogue_label(key) for key in DIALOGUE_LABELS}
        behavior_layout.addWidget(
            SettingsSection(
                t("settings.dlg.voice_style"),
                [
                    SettingRow(
                        "dialogue_mode",
                        t("settings.dlg.voice_style"),
                        t("settings.dlg.how_fish_talks_self_talk"),
                        ResponsiveActionRow(self.dialogue_mode_select, [self.dialogue_adopt_btn]),
                    ),
                    SettingRow(
                        "dialogue_scope",
                        t("settings.dlg.lines_custom_mode_only"),
                        t("settings.dlg.who_per_event_lines_below"),
                        self.dialogue_scope_select,
                        stacked=True,
                    ),
                ],
                behavior_content,
            )
        )
        behavior_layout.addWidget(
            SettingsCard(
                [
                    SettingRow(
                        "dialogue_template_actions",
                        t("settings.dlg.bubble_text_template_json"),
                        t("settings.dlg.copy_template_every_current_bubble"),
                        self.dialogue_template_actions,
                        stacked=True,
                    ),
                ],
                behavior_content,
            )
        )
        behavior_layout.addWidget(
            SettingsCard(
                [
                    SettingRow(
                        f"dialogue_{key}",
                        labels.get(key, key),
                        t("settings.dlg.leave_blank_use_base_style") + (dialogue_params_hint(key) or t("settings.dlg.none")),
                        edit,
                        stacked=True,
                    )
                    for key, edit in self.dialogue_phrase_edits.items()
                ],
                behavior_content,
            )
        )
        behavior_layout.addWidget(
            SettingsSection(
                t("settings.dlg.do_reminders"),
                [
                    SettingRow(
                        "todo_reminder_enabled", t("settings.dlg.do_reminders"), t("settings.dlg.remind_you_time_bubble_desktop"), self.todo_reminder_check
                    ),
                    SettingRow(
                        "todo_reminder_lead_minutes", t("settings.dlg.remind_early"), t("settings.dlg.minutes_before_due_time_remind"), self.todo_reminder_lead_spin
                    ),
                ],
                behavior_content,
            )
        )
        behavior_layout.addStretch(1)
        self._add_page(t("settings.dlg.fish_behavior"), "play", self._page_shell(t("settings.dlg.fish_behavior"), behavior_content))

        appearance_content = QWidget()
        appearance_layout = QVBoxLayout(appearance_content)
        appearance_layout.setContentsMargins(0, 0, 0, 0)
        appearance_layout.setSpacing(16)
        appearance_layout.addWidget(
            SettingsSection(
                t("settings.dlg.fish_display"),
                [
                    SettingRow("scale", t("settings.dlg.fish_size"), t("settings.dlg.how_big_fish_appears_desktop"), self.scale_combo),
                    SettingRow(
                        "bubble_text_scale",
                        t("settings.dlg.bubble_text_size"),
                        t("settings.dlg.size_text_bubbles_bubble_font"),
                        self.bubble_text_scale_spin,
                    ),
                    SettingRow("pet_opacity", t("settings.dlg.opacity"), t("settings.dlg.overall_transparency_fish_window_100"), self.pet_opacity_spin),
                    # 「气泡方案」行归「互动 · 自言自语」（settings_interaction 构建）。
                ],
                appearance_content,
            )
        )
        appearance_layout.addWidget(
            SettingsSection(
                t("settings.dlg.menu_appearance"),
                [
                    SettingRow("menu_theme", t("settings.dlg.color_theme"), t("settings.dlg.follow_system_always_use_light"), self.menu_theme_select),
                    SettingRow("menu_density", t("settings.dlg.menu_density"), t("settings.dlg.item_height_group_spacing_new"), self.menu_density_select),
                    SettingRow("menu_radius", t("settings.dlg.corner_radius"), t("settings.dlg.corner_radius_new_right_click"), self.menu_radius_select),
                    SettingRow("menu_font", t("settings.dlg.ui_font"), t("settings.dlg.font_used_by_new_menu"), self.menu_font_select),
                    SettingRow("menu_font_size", t("settings.dlg.ui_font_size"), t("settings.dlg.font_size_main_menu_all"), self.menu_font_size_select),
                    SettingRow("menu_translucent", t("settings.dlg.translucent_menu"), t("settings.dlg.use_translucent_modern_like_floating"), self.menu_translucent_check),
                    SettingRow("menu_opacity", t("settings.dlg.surface_opacity"), t("settings.dlg.how_much_desktop_shows_through"), self.menu_opacity_spin),
                ],
                appearance_content,
            )
        )
        if self.ai_page is not None:
            appearance_layout.addWidget(SettingsSection(t("settings.dlg.ai_chat_appearance"), self.ai_page.appearance_rows(), appearance_content))
        appearance_layout.addWidget(
            SettingsSection(
                t("settings.dlg.light_theme"),
                [
                    SettingRow("light_background", t("settings.dlg.background"), t("settings.dlg.floating_background_light_menu"), self.light_background_picker),
                    SettingRow("light_foreground", t("settings.dlg.text_color"), t("settings.dlg.main_text_icon_color_light"), self.light_foreground_picker),
                    SettingRow("light_hover", t("settings.dlg.hover_color"), t("settings.dlg.background_menu_item_under_mouse"), self.light_hover_picker),
                ],
                appearance_content,
            )
        )
        appearance_layout.addWidget(
            SettingsSection(
                t("settings.dlg.dark_theme"),
                [
                    SettingRow("dark_background", t("settings.dlg.background"), t("settings.dlg.floating_background_dark_menu"), self.dark_background_picker),
                    SettingRow("dark_foreground", t("settings.dlg.text_color"), t("settings.dlg.main_text_icon_color_dark"), self.dark_foreground_picker),
                    SettingRow("dark_hover", t("settings.dlg.hover_color"), t("settings.dlg.background_menu_item_under_mouse"), self.dark_hover_picker),
                ],
                appearance_content,
            )
        )
        appearance_layout.addWidget(
            SettingsSection(
                t("settings.dlg.easter_egg_entry"),
                [
                    SettingRow("egg_enabled", t("settings.dlg.show_easter_egg"), t("settings.dlg.whether_easter_egg_entry_shows"), self.egg_enabled_check),
                    SettingRow("egg_title", t("settings.dlg.entry_title"), t("settings.dlg.text_shown_right_round_avatar"), self.egg_title_edit),
                    SettingRow("egg_hint", t("settings.dlg.right_side_hint"), t("settings.dlg.short_hint_shown_after_mouse"), self.egg_hint_edit),
                    SettingRow("egg_avatar", t("settings.dlg.avatar_image"), t("settings.dlg.use_absolute_path_common_image"), self.egg_avatar_picker),
                    SettingRow("egg_image_dir", t("settings.dlg.pop_up_image_folder"), t("settings.dlg.use_absolute_path_each_click"), self.egg_image_dir_picker),
                ],
                appearance_content,
            )
        )
        appearance_layout.addStretch(1)
        self._add_page(t("settings.dlg.appearance"), "appearance", self._page_shell(t("settings.dlg.appearance"), appearance_content))

        menu_content = QWidget()
        menu_page_layout = QVBoxLayout(menu_content)
        menu_page_layout.setContentsMargins(0, 0, 0, 0)
        menu_page_layout.setSpacing(18)
        self.menu_template_select = ModernSelect(menu_content, width=156)
        self.menu_template_select.addItem(t("settings.dlg.new_menu"), "modern")
        self.menu_template_select.addItem(t("settings.dlg.legacy_menu"), "legacy")
        self.menu_template_select.setCurrentData(str(self.config.get("context_menu_template", "modern") or "modern"))
        menu_available_actions = set(MENU_ACTIONS.ids)
        if sys.platform != "win32":
            menu_available_actions.discard("proactive_screen")
        if not self.include_ai:
            menu_available_actions.difference_update({"chat", "look_screen", "balance", "proactive_screen"})
        self.menu_available_actions = frozenset(menu_available_actions)
        menu_enabled_actions = set(menu_available_actions)
        if not self.config.get("quick_launch_apps", DEFAULT_QUICK_LAUNCH_APPS):
            menu_enabled_actions.discard("quick_launch")
        if not self.config.get("menu_easter_egg", DEFAULT_MENU_EASTER_EGG).get("enabled", True):
            menu_enabled_actions.discard("ojingjing")
        self.menu_layout_editor = MenuLayoutEditor(
            self.config.get("context_menu_layout"),
            menu_content,
            available_actions=menu_available_actions,
            enabled_actions=menu_enabled_actions,
        )
        menu_page_layout.addWidget(
            SettingsSection(
                t("settings.dlg.content_layout"),
                [
                    SettingRow("menu_template", t("settings.dlg.menu_mode"), t("settings.dlg.legacy_menu_only_kept_migration"), self.menu_template_select),
                    SettingRow("context_menu_layout", t("settings.dlg.menu_layout"), t("settings.dlg.adjust_visibility_order_nesting_edit"), self.menu_layout_editor, stacked=True),
                ],
                menu_content,
            )
        )
        menu_page_layout.addStretch(1)
        self._add_page(t("settings.dlg.menu"), "application", self._page_shell(t("settings.dlg.menu"), menu_content))

        launcher_content = QWidget()
        launcher_layout = QVBoxLayout(launcher_content)
        launcher_layout.setContentsMargins(0, 0, 0, 0)
        launcher_layout.setSpacing(18)
        self.quick_launch_editor = QuickLaunchEditor(
            self.config.get("quick_launch_apps", DEFAULT_QUICK_LAUNCH_APPS),
            launcher_content,
        )
        launcher_layout.addWidget(
            SettingsSection(
                t("settings.dlg.configured_apps"),
                [
                    SettingRow(
                        "quick_launch_apps",
                        t("settings.dlg.app_quick_launch"),
                        t("settings.dlg.these_apps_appear_their_icon"),
                        self.quick_launch_editor,
                        stacked=True,
                    ),
                ],
                launcher_content,
            )
        )
        launcher_layout.addStretch(1)
        self._add_page(t("settings.dlg.quick_launch"), "application", self._page_shell(t("settings.dlg.quick_launch"), launcher_content))

        if sys.platform == "win32" and self.include_ai:
            self._add_page(t("settings.dlg.screen_awareness"), "screen", self._page_shell(t("settings.dlg.screen_awareness"), self._proactive_page_content()))

        # AI rows are composed directly into the final capability domain by
        # _rebuild_domain_navigation. Do not temporarily hand the controller
        # widget to a QScrollArea: that creates a second Qt ownership path when
        # its rows are reparented into the shared card system.

        # 语音报时设置页（行在 _rebuild_domain_navigation 中拾入「语音」总域）
        from .voice_chime_settings import VoiceChimeSettingsPage

        self.voice_chime_page = VoiceChimeSettingsPage(self.config, self)
        self.voice_chime_page.preview_requested.connect(self._on_voice_chime_preview)

        # 节日提醒设置页（行在 _rebuild_domain_navigation 中拾入「语音」总域）
        from .festival_settings import FestivalSettingsPage

        self.festival_page = FestivalSettingsPage(self.config, self)

        self._rebuild_domain_navigation()
        self.sidebar.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sidebar.setCurrentRow(0)
        if self.initial_page:
            self.select_page(self.initial_page)
        self._search_rows = self.findChildren(SettingRow)
        self._search_matches: list[SettingRow] = []
        self._search_index = -1
        self.search_edit.textChanged.connect(self._search_settings)

        self.self_talk_check.toggled.connect(self._update_self_talk_controls)
        self.menu_translucent_check.toggled.connect(self._update_translucency_controls)
        self.island_enabled_check.toggled.connect(self._update_island_controls)
        self.island_icon_check.toggled.connect(self._update_island_icon_controls)
        self.island_info_check.toggled.connect(self._update_island_info_controls)
        self.egg_enabled_check.toggled.connect(self._update_egg_controls)
        self.egg_enabled_check.toggled.connect(self._sync_menu_action_states)
        self.quick_launch_editor.changed.connect(self._sync_menu_action_states)
        self.collision_enabled_check.toggled.connect(self._update_collision_controls)
        self.collision_sound_check.toggled.connect(self._update_collision_sound_controls)
        if hasattr(self, "pro_enabled_check"):
            self.pro_enabled_check.toggled.connect(self._update_proactive_controls)
            self.pro_idle_check.toggled.connect(self._update_proactive_idle_controls)
        self.spawn_inherit_size_check.toggled.connect(self._update_spawn_size_controls)
        self.golden_spin_click_check.toggled.connect(self._update_golden_spin_controls)
        self.click_self_talk_check.toggled.connect(self._update_click_self_talk_controls)
        self._update_self_talk_controls(self.self_talk_check.isChecked())
        self._update_click_self_talk_controls(self.click_self_talk_check.isChecked())
        self._update_translucency_controls(self.menu_translucent_check.isChecked())
        self._update_island_controls(self.island_enabled_check.isChecked())
        self._update_egg_controls(self.egg_enabled_check.isChecked())
        self._sync_menu_action_states()
        self._update_collision_controls(self.collision_enabled_check.isChecked())
        if hasattr(self, "pro_enabled_check"):
            self._update_proactive_controls(self.pro_enabled_check.isChecked())
        self._update_spawn_size_controls(self.spawn_inherit_size_check.isChecked())
        # 初始同步须在全部 SettingRow 构建完成后执行，否则 findChild 找不到行
        self._update_click_sound_controls(self.click_sound_check.isChecked())
        self._update_golden_spin_controls(self.golden_spin_click_check.isChecked())
        self._update_agent_sound_controls(self.agent_sound_check.isChecked())
        self._update_agent_sound_subcontrols()

        self.menu_theme_select.currentIndexChanged.connect(self._apply_selected_theme)
        self._apply_selected_theme()
        # 行全部就位后收敛台词编辑可见性：初始层若为某 Agent 专属则隐藏公共事件行
        settings_pet_controls._apply_dialogue_scope_rows(self)
        # 行全部就位后标注窗口级键的生效范围（overlay 一窗多宠：只有子宠页需要）
        settings_pet_controls._apply_window_scope_rows(self)
        if self.standalone:
            # 独立进程本地宿主：试听改本地播放、节日试听本地演示、无 parent 时
            # 读 runtime 状态文件避让肥鱼。逻辑全在 pet/settings_standalone.py，
            # 这里只做接线（本文件有行数预算）。
            from .settings_standalone import install_standalone_hooks

            install_standalone_hooks(self)

    def _sync_menu_action_states(self, *_args) -> None:
        enabled = set(self.menu_available_actions)
        if not self.quick_launch_editor.apps():
            enabled.discard("quick_launch")
        if not self.egg_enabled_check.isChecked():
            enabled.discard("ojingjing")
        self.menu_layout_editor.set_enabled_actions(enabled)

    def _build_pet_controls(self) -> None:
        """Compatibility delegation (settings_pet_controls.build_pet_controls)."""
        settings_pet_controls.build_pet_controls(self)

    def _build_file_interpret_controls(self) -> None:
        """「文件识别」域控件（settings_file_interpret 构建，行数预算原因不在本文件展开）。"""
        settings_file_interpret.create_file_interpret_controls(self)

    def _build_proactive_controls(self) -> None:
        """主动识屏页控件（仅 Windows + 有聊天能力时挂载）。"""
        from .proactive import effective_proactive_config

        pro = effective_proactive_config(self.config.get("proactive_screen", {}))

        self.pro_enabled_check = ToggleSwitch(self)
        self.pro_enabled_check.setChecked(bool(pro["enabled"]))
        self.pro_dryrun_check = ToggleSwitch(self)
        self.pro_dryrun_check.setChecked(bool(pro["dry_run"]))

        self.pro_preset_select = ModernSelect(self, width=160)
        for key, label in (
            ("balanced", t("settings.dlg.balanced_recommended")),
            ("quiet", t("settings.dlg.quiet")),
            ("active", t("settings.dlg.lively")),
            ("custom", t("settings.dlg.custom_values")),
        ):
            self.pro_preset_select.addItem(label, key)
        idx = {"quiet": 1, "balanced": 0, "active": 2, "custom": 3}.get(pro["preset"], 0)
        self.pro_preset_select.setCurrentIndex(idx)
        self.pro_preset_select.currentIndexChanged.connect(self._on_pro_preset_changed)

        self.pro_dwell_spin = BrowserSpinBox(self)
        self.pro_dwell_spin.setRange(15, 600)
        self.pro_dwell_spin.setValue(int(pro["dwell_seconds"]))

        self.pro_cooldown_spin = BrowserDoubleSpinBox(self)
        self.pro_cooldown_spin.setRange(0.5, 7200)
        self.pro_cooldown_spin.setDecimals(2)
        self.pro_cooldown_unit = ModernSelect(self, width=80)
        self.pro_cooldown_unit.addItem(t("settings.dlg.min"), "min")
        self.pro_cooldown_unit.addItem(t("settings.dlg.s"), "sec")
        self._pro_set_cooldown_display(float(pro["cooldown_minutes"]))
        self.pro_cooldown_unit.currentIndexChanged.connect(self._on_pro_cooldown_unit_changed)

        self.pro_min_interval_spin = BrowserSpinBox(self)
        self.pro_min_interval_spin.setRange(30, 3600)
        self.pro_min_interval_spin.setValue(int(pro["min_request_interval_seconds"]))

        self.pro_cap_spin = BrowserSpinBox(self)
        self.pro_cap_spin.setRange(1, 9999)
        self.pro_cap_spin.setValue(int(pro["daily_cap"]))

        self.pro_idle_check = ToggleSwitch(self)
        self.pro_idle_check.setChecked(bool(pro["require_idle"]))
        self.pro_idle_spin = BrowserSpinBox(self)
        self.pro_idle_spin.setRange(5, 3600)
        raw_idle = (self.config.get("proactive_screen", {}) or {}).get("min_idle_seconds", 30)
        self.pro_idle_spin.setValue(int(raw_idle or 30))

        self.pro_through_check = ToggleSwitch(self)
        self.pro_through_check.setChecked(bool(pro["allow_when_mouse_through"]))
        self.pro_precue_check = ToggleSwitch(self)
        self.pro_precue_check.setChecked(bool(pro["pre_cue"]))
        self.pro_free_check = ToggleSwitch(self)
        self.pro_free_check.setChecked(bool(pro["prefer_free_provider"]))

        self.pro_whitelist_edit = QPlainTextEdit(self)
        self.pro_whitelist_edit.setPlaceholderText(t("settings.dlg.msedge_exe_title_meeting"))
        self.pro_whitelist_edit.setPlainText("\n".join(str(x) for x in pro["whitelist"]))
        self.pro_whitelist_edit.setMinimumHeight(72)

        self.pro_add_btn = TiltButton(t("settings.dlg.add_from_foreground_window"), self)
        self.pro_add_btn.setProperty("variant", "ghost")
        self.pro_add_btn.clicked.connect(self._on_pro_add_foreground)
        self._pro_add_timer = QTimer(self)
        self._pro_add_timer.setSingleShot(True)
        self._pro_add_timer.timeout.connect(self._do_pro_add_foreground)

        self.pro_clear_mem_btn = TiltButton(t("settings.dlg.clear_companion_memory"), self)
        self.pro_clear_mem_btn.setProperty("variant", "ghost")
        self.pro_clear_mem_btn.clicked.connect(self._on_pro_clear_memory)

    def _pro_set_cooldown_display(self, minutes: float) -> None:
        unit = "sec" if minutes < 1 else "min"
        self._pro_apply_cooldown_unit(unit, minutes)

    def _pro_apply_cooldown_unit(self, unit: str, minutes: float) -> None:
        self.pro_cooldown_unit.blockSignals(True)
        self.pro_cooldown_unit.setCurrentIndex(1 if unit == "sec" else 0)
        if unit == "sec":
            self.pro_cooldown_spin.setRange(30, 7200)
            self.pro_cooldown_spin.setDecimals(0)
            self.pro_cooldown_spin.setValue(min(7200, max(30, round(minutes * 60))))
        else:
            self.pro_cooldown_spin.setRange(0.5, 120)
            self.pro_cooldown_spin.setDecimals(2)
            self.pro_cooldown_spin.setValue(min(120.0, max(0.5, minutes)))
        self._pro_cooldown_last_unit = unit
        self.pro_cooldown_unit.blockSignals(False)

    def _on_pro_cooldown_unit_changed(self) -> None:
        old = getattr(self, "_pro_cooldown_last_unit", "min")
        v = float(self.pro_cooldown_spin.value())
        minutes = v / 60.0 if old == "sec" else v
        self._pro_apply_cooldown_unit(self.pro_cooldown_unit.currentData(), minutes)

    def _pro_cooldown_minutes(self) -> float:
        v = float(self.pro_cooldown_spin.value())
        return v / 60.0 if self.pro_cooldown_unit.currentData() == "sec" else v

    def _on_pro_preset_changed(self, _index: int) -> None:
        from .proactive import PRESET_DEFAULTS

        vals = PRESET_DEFAULTS.get(self.pro_preset_select.currentData())
        if vals:
            self.pro_dwell_spin.setValue(vals["dwell_seconds"])
            self._pro_set_cooldown_display(float(vals["cooldown_minutes"]))
            self.pro_cap_spin.setValue(vals["daily_cap"])

    def _on_pro_add_foreground(self) -> None:
        self.pro_add_btn.setEnabled(False)
        self.pro_add_btn.setText(t("settings.dlg.switch_target_window_within_3"))
        self._pro_add_timer.start(3000)

    def _do_pro_add_foreground(self) -> None:
        self.pro_add_btn.setEnabled(True)
        self.pro_add_btn.setText(t("settings.dlg.add_from_foreground_window"))
        from . import vision

        info = vision.foreground_window_info()
        if not info:
            QMessageBox.information(self, t("settings.dlg.add_foreground_window"), t("settings.dlg.no_usable_foreground_window_was"))
            return
        proc = str(info.get("process", "")).strip()
        title = str(info.get("title", "")).strip()
        box = QMessageBox(self)
        box.setWindowTitle(t("settings.dlg.add_allow_list"))
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(t("settings.dlg.foreground_window_found_process_v", v=proc or t("settings.dlg.unknown"), v2=title or t("settings.dlg.empty")))
        btn_proc = box.addButton(t("settings.dlg.by_app_recommended"), QMessageBox.ButtonRole.AcceptRole)
        btn_title = box.addButton(t("settings.dlg.by_title_keyword"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        lines = [x.strip() for x in self.pro_whitelist_edit.toPlainText().splitlines() if x.strip()]
        if box.clickedButton() is btn_proc and proc and proc not in lines:
            lines.append(proc)
        elif box.clickedButton() is btn_title and title:
            rule = f"title:*{title}*"
            if rule not in lines:
                lines.append(rule)
        else:
            return
        self.pro_whitelist_edit.setPlainText("\n".join(lines))

    def _on_pro_clear_memory(self) -> None:
        from .proactive import ProactiveMemory

        # clear() 返回本次是否真的清空：设置页是独立进程，主进程可能正在写同一
        # 份记忆文件（拿不到跨进程锁 = 这次没清）。失败必须如实提示，不能无条件
        # 报"已清空"——那正是用户看到的"清了还在"。
        cleared = ProactiveMemory(self.config.dir / "proactive_screen_memory.json").clear()
        if cleared is False:
            QMessageBox.warning(
                self,
                t("settings.dlg.couldn_t_clear_companion_memory"),
                t("settings.dlg.companion_memory_couldn_t_cleared"),
            )
            return
        QMessageBox.information(self, t("settings.dlg.companion_memory"), t("settings.dlg.screen_awareness_short_term_companion"))

    def _proactive_page_content(self) -> QWidget:
        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        layout.addWidget(
            SettingsSection(
                t("settings.dlg.switch_pace"),
                [
                    SettingRow(
                        "proactive_enabled",
                        t("settings.dlg.turn_screen_awareness"),
                        t("settings.dlg.she_glances_at_app_you"),
                        self.pro_enabled_check,
                    ),
                    SettingRow("proactive_dry_run", t("settings.dlg.dry_run_mode"), t("settings.dlg.when_trigger_only_writes_log"), self.pro_dryrun_check),
                    SettingRow(
                        "proactive_preset",
                        t("settings.dlg.companion_pace_preset"),
                        t("settings.dlg.balanced_45s_5min_15_quiet"),
                        self.pro_preset_select,
                    ),
                ],
                content,
            )
        )
        layout.addWidget(
            SettingsSection(
                t("settings.dlg.frequency_used_by_custom_preset"),
                [
                    SettingRow("proactive_dwell", t("settings.dlg.window_dwell_threshold"), t("settings.dlg.same_foreground_window_has_stay"), self.pro_dwell_spin),
                    SettingRow("proactive_cooldown", t("settings.dlg.care_cooldown"), t("settings.dlg.shortest_gap_between_two_check"), self._pro_cooldown_row()),
                    SettingRow("proactive_min_interval", t("settings.dlg.minimum_request_gap"), t("settings.dlg.hard_protection_free_models_don"), self.pro_min_interval_spin),
                    SettingRow("proactive_daily_cap", t("settings.dlg.daily_request_cap"), t("settings.dlg.most_screen_requests_per_day"), self.pro_cap_spin),
                ],
                content,
            )
        )
        layout.addWidget(
            SettingsSection(
                t("settings.dlg.triggers"),
                [
                    SettingRow("proactive_require_idle", t("settings.dlg.only_when_i_m_idle"), t("settings.dlg.when_checked_won_t_interrupt"), self.pro_idle_check),
                    SettingRow("proactive_idle_seconds", t("settings.dlg.idle_seconds"), t("settings.dlg.option_above_trigger_only_after"), self.pro_idle_spin),
                    SettingRow("proactive_through", t("settings.dlg.keep_looking_while_click_through"), t("settings.dlg.whether_keeps_working_while_fish"), self.pro_through_check),
                    SettingRow("proactive_pre_cue", t("settings.dlg.heads_up_before_look"), t("settings.dlg.say_let_me_take_look"), self.pro_precue_check),
                    SettingRow(
                        "proactive_free",
                        t("settings.dlg.prefer_separate_vision_config"),
                        t("settings.dlg.if_provider_has_separate_vision"),
                        self.pro_free_check,
                    ),
                ],
                content,
            )
        )
        layout.addWidget(
            SettingsSection(
                t("settings.dlg.allow_list"),
                [
                    SettingRow(
                        "proactive_whitelist",
                        t("settings.dlg.allow_list_one_per_line"),
                        t("settings.dlg.process_name_such_as_msedge"),
                        self.pro_whitelist_edit,
                        stacked=True,
                    ),
                    SettingRow("proactive_whitelist_add", t("settings.dlg.quick_add"), t("settings.dlg.switch_target_window_within_3_2"), self.pro_add_btn),
                    SettingRow("proactive_memory_clear", t("settings.dlg.companion_memory"), t("settings.dlg.only_process_names_activity_categories"), self.pro_clear_mem_btn),
                ],
                content,
            )
        )
        layout.addStretch(1)
        return content

    def _pro_cooldown_row(self) -> QWidget:
        row = QWidget(self)
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        h.addWidget(self.pro_cooldown_spin)
        h.addWidget(self.pro_cooldown_unit)
        return row

    def _update_self_talk_controls(self, enabled: bool) -> None:
        """周期气泡（``self_talk``）的细项显隐。

        点击侧（``click_self_talk*`` / ``click_talk_bindings``）**不在这里**：它们是
        独立开关的后续项，见 :meth:`_update_click_self_talk_controls`。绑在一起会让
        「只想点击听声」的用户在设置页里连开关都看不到。
        """
        keys = (
            "self_talk_duration",
            "self_talk_min",
            "self_talk_max",
            "self_talk_texts",
            "self_talk_images",
            "self_talk_image_scale",
            "self_talk_image_max_edge",
            "self_talk_image_chance",
        )
        self._set_setting_rows_visible(keys, enabled)

    def _update_click_self_talk_controls(self, enabled: bool) -> None:
        """点击自言自语（``click_self_talk``）的后续项显隐。

        预缓存也跟这里：只有点击链路才会把台词**读出来**（周期气泡只显示不朗读），
        所以点击开关关着时预缓存没有意义。
        """
        keys = (
            "click_self_talk_speak",
            "click_self_talk_precache",
            "click_talk_bindings",
        )
        self._set_setting_rows_visible(keys, enabled, dependency="click_self_talk")

    def _update_island_controls(self, enabled: bool) -> None:
        settings_pet_controls._update_island_controls(self, enabled)

    def _update_island_icon_controls(self, enabled: bool) -> None:
        settings_pet_controls._update_island_icon_controls(self, enabled)

    def _update_island_info_controls(self, enabled: bool) -> None:
        settings_pet_controls._update_island_info_controls(self, enabled)

    def _update_egg_controls(self, enabled: bool) -> None:
        self._set_setting_rows_visible(
            ("egg_title", "egg_hint", "egg_avatar", "egg_image_dir"),
            enabled,
            dependency="egg_enabled",
        )

    def _update_collision_controls(self, enabled: bool) -> None:
        self._set_setting_rows_visible(
            (
                "collision_sound_enabled",
                "collision_restitution",
                "collision_friction",
                "collision_mass_scale",
                "collision_impulse_cap",
                "collision_sound_volume",
            ),
            enabled,
            dependency="collision_enabled",
        )
        self._update_collision_sound_controls(self.collision_sound_check.isChecked())

    def _update_collision_sound_controls(self, enabled: bool) -> None:
        self._set_setting_rows_visible(
            ("collision_sound_volume",),
            enabled,
            dependency="collision_sound_enabled",
        )

    def _update_proactive_controls(self, enabled: bool) -> None:
        self._set_setting_rows_visible(
            (
                "proactive_dry_run",
                "proactive_preset",
                "proactive_dwell",
                "proactive_cooldown",
                "proactive_min_interval",
                "proactive_daily_cap",
                "proactive_require_idle",
                "proactive_idle_seconds",
                "proactive_through",
                "proactive_pre_cue",
                "proactive_free",
                "proactive_whitelist",
                "proactive_whitelist_add",
                "proactive_memory_clear",
            ),
            enabled,
            dependency="proactive_enabled",
        )
        self._update_proactive_idle_controls(self.pro_idle_check.isChecked())

    def _update_proactive_idle_controls(self, enabled: bool) -> None:
        self._set_setting_rows_visible(
            ("proactive_idle_seconds",),
            enabled,
            dependency="proactive_require_idle",
        )

    def _set_setting_rows_visible(
        self,
        keys: tuple[str, ...],
        visible: bool,
        *,
        dependency: str = "parent",
    ) -> None:
        """Show dependent settings as a complete group and repair card dividers."""
        cards: set[SettingsCard] = set()
        sections: set[SettingsSection] = set()
        for key in keys:
            row = self.findChild(SettingRow, f"settingRow_{key}")
            if row is None:
                continue
            dependencies = getattr(row, "_visibility_dependencies", {})
            dependencies[dependency] = bool(visible)
            row._visibility_dependencies = dependencies
            row.setVisible(all(dependencies.values()))
            card = row.parentWidget()
            if isinstance(card, SettingsCard):
                cards.add(card)
                section = card.parentWidget()
                if isinstance(section, SettingsSection):
                    sections.add(section)
        for section in sections:
            section.refresh_dependency_visibility()
        for card in cards:
            card.refresh_separators()

    def _populate_menu_fonts(self) -> None:
        if shiboken6.isValid(self) is False or self._menu_fonts_populated:
            return
        self._menu_fonts_populated = True
        appearance = self.config.get("context_menu_appearance", DEFAULT_CONTEXT_MENU_APPEARANCE)
        for family in _system_font_families():
            if self.menu_font_select.findData(family) < 0:
                self.menu_font_select.addItem(family, family)
        current_font = str(appearance.get("ui_font") or "system")
        if self.menu_font_select.findData(current_font) < 0:
            self.menu_font_select.addItem(current_font, current_font)
        self.menu_font_select.setCurrentData(current_font)

    def _open_click_talk_bindings(self) -> None:
        from .click_talk_dialog import ClickTalkBindingsDialog

        click_names = None
        parent = self.parent()
        if parent is not None and hasattr(parent, "clicks") and parent.clicks:
            click_names = list(parent.clicks)
        dialog = ClickTalkBindingsDialog(self.config, click_names=click_names, parent=self)
        dialog.exec()

    def _preview_click_sound(self) -> None:
        """试听当前选择的点击音效配置（不保存配置）。"""
        from .click_sound import choose_sound, play_sound, resolve_click_sound_candidates

        pack = self.click_sound_picker.value()
        candidates = resolve_click_sound_candidates(pack, self.config.dir)
        sound_file = choose_sound(candidates)
        if sound_file:
            vol = float(self.click_sound_volume_spin.value()) / 100.0
            play_sound(sound_file, volume=vol)

    def _preview_agent_sound(self, event_name: str) -> None:
        """试听当前填写的 Agent 音效（不保存配置、不触发 Agent 业务逻辑）。"""
        from .click_sound import play_sound, resolve_builtin_sound

        picker = {
            "start": self.agent_sound_start_picker,
            "done": self.agent_sound_done_picker,
            "error": self.agent_sound_error_picker,
        }.get(event_name)
        if picker is None:
            return
        path_str = picker.text().strip()
        if not path_str:
            path_str = f"builtin:agent-{event_name}"

        target = None
        if path_str.startswith("builtin:"):
            target = resolve_builtin_sound(path_str)
        else:
            p = Path(path_str).expanduser()
            if p.is_file():
                target = p

        if target:
            vol = float(self.agent_sound_volume_spin.value()) / 100.0
            play_sound(target, volume=vol)

    def _import_dialogue_template_json(self) -> None:
        """Import a complete persona template from the inline JSON editor."""
        settings_pet_controls._import_dialogue_template_json(self)

    def _dialogue_flush_scope(self, scope: str | None = None) -> None:
        """把当前编辑区的文本快照写回 scope buffer（切换/保存前调用）。"""
        settings_pet_controls._dialogue_flush_scope(self, scope)

    def _adopt_builtin_phrases(self, confirm=None) -> bool:
        return settings_pet_controls._adopt_builtin_phrases(self, confirm)

    def _on_dialogue_scope_changed(self, index: int) -> None:
        """切换 global/某 Agent 专属文案编辑层：flush 当前层后载入目标层内容。"""
        settings_pet_controls._on_dialogue_scope_changed(self, index)

    def _dialogue_scope_values(self, scope: str) -> dict[str, list[str]]:
        """scope buffer 某层的非空事件 → list[str]（供保存/导出）。"""
        return settings_pet_controls._dialogue_scope_values(self, scope)

    def _dialogue_phrase_values(self) -> dict[str, list[str]]:
        return settings_pet_controls._dialogue_phrase_values(self)

    def _current_dialogue_template(self) -> dict:
        return settings_pet_controls._current_dialogue_template(self)

    def _export_dialogue_template(self) -> None:
        """Export the complete current template to the clipboard (no file dialog)."""
        settings_pet_controls._export_dialogue_template(self)

    def _update_click_sound_controls(self, enabled: bool) -> None:
        for row_key in ("click_sound_pack", "click_sound_volume", "click_sound_preview"):
            row = self.findChild(SettingRow, f"settingRow_{row_key}")
            if row is not None:
                row.setVisible(bool(enabled))
                card = row.parentWidget()
                if isinstance(card, SettingsCard):
                    card.refresh_separators()

    def _update_golden_spin_controls(self, enabled: bool) -> None:
        """“点击触发黄金回旋”总开关控制“跳过动画”子开关可见性。"""
        row = self.findChild(SettingRow, "settingRow_golden_spin_direct")
        if row is not None:
            row.setVisible(bool(enabled))
            card = row.parentWidget()
            if isinstance(card, SettingsCard):
                card.refresh_separators()

    def _update_agent_sound_controls(self, enabled: bool) -> None:
        """Agent 音效总开关联动控制整组子项可见性/可用性。"""
        for row_key in ("agent_sound_start", "agent_sound_done", "agent_sound_error", "agent_sound_volume", "agent_sound_cooldown"):
            row = self.findChild(SettingRow, f"settingRow_{row_key}")
            if row is not None:
                row.setVisible(bool(enabled))
                card = row.parentWidget()
                if isinstance(card, SettingsCard):
                    card.refresh_separators()
        if enabled:
            self._update_agent_sound_subcontrols()

    def _update_agent_sound_subcontrols(self) -> None:
        """单事件关闭时保留开关，仅隐藏其路径选择器和试听按钮。"""
        for toggle, picker, preview in (
            (self.agent_sound_start_check, self.agent_sound_start_picker, self.agent_sound_start_preview),
            (self.agent_sound_done_check, self.agent_sound_done_picker, self.agent_sound_done_preview),
            (self.agent_sound_error_check, self.agent_sound_error_picker, self.agent_sound_error_preview),
        ):
            visible = toggle.isChecked()
            picker.setVisible(visible)
            preview.setVisible(visible)

    def _update_translucency_controls(self, enabled: bool) -> None:
        self._set_setting_rows_visible(("menu_opacity",), enabled)

    def _update_spawn_size_controls(self, inherit_size: bool) -> None:
        """“生小肥鱼继承大小”关闭时才显示独立小肥鱼大小选择。"""
        self._set_setting_rows_visible(
            ("spawn_scale",),
            not bool(inherit_size),
            dependency="spawn_inherit_size",
        )
        self._set_setting_rows_visible(("spawn_smaller_than_main",), bool(inherit_size), dependency="spawn_inherit_size")

    def _on_clear_spawned_pets(self) -> None:
        """一键静默退出所有小肥鱼（slot-N）；它们的设置与数据保留。

        优先走 PetWindow 上已接线的 ``on_clear_spawned_pets``（= AppShell 路径，
        含进程内子窗前置于关闭）；拿不到回调（独立设置进程：本进程既无肥鱼壳也
        无 sprite 世界）时统一走 **D12 指令通道**：写指令文件，由主进程
        （OverlayShell / AppShell）经 config 目录 watcher + 轮询消费；按本配置
        身份回填 target，语义收窄到"这一只"（主身份 = 全部）。

        4.4a：legacy 的跨进程 taskkill 回退（child_pet_cleanup：runtime 标记 +
        slot 锁 + taskkill）随多进程多宠退役层停用——两个拓扑现在共用同一条
        指令通道，不再有"按钮静默失效"的拓扑分叉。

        批 I：无确认框无结果框（操作不删数据可重新生成，子肥鱼消失即反馈）。
        """
        callback = getattr(self.parentWidget(), "on_clear_spawned_pets", None)
        if callable(callback):
            callback()
            return
        from .overlay_settings_command import (
            CMD_EXIT_SPAWNED_PETS,
            slot_from_instance_id,
            write_command,
        )
        target = slot_from_instance_id(self.config.instance_id)
        if write_command(self.config.dir, CMD_EXIT_SPAWNED_PETS, target=target):
            logging.info("退出子肥鱼：已写下指令（target=%s，主进程消费）", target)
        else:
            logging.warning("退出子肥鱼：写指令文件失败，本次未执行")

    def _apply_agent_sound_enabled_now(self, checked: bool) -> None:
        """音效总开关即时生效，不等对话框关闭（合并写回，不动其他 agent_link 键）。"""
        agent_cfg = dict(self.config.get("agent_link", {}))
        agent_cfg["sound_enabled"] = bool(checked)
        self.config.set("agent_link", agent_cfg)
        self.config.save()

    def _apply_click_sound_enabled_now(self, checked: bool) -> None:
        """点击音效开关即时生效，不等对话框关闭。"""
        self.config.set("click_sound_enabled", bool(checked))
        self.config.save()
        if bool(checked):
            # 开启后立即预热，保证不关闭对话框直接试听/点击也有声音。
            warm_click_sound_effects(
                self.config.get("click_sound_pack"),
                data_dir=self.config.dir,
            )

    def move_away_from_pet(self) -> None:
        """把窗口定位到不与肥鱼相交的位置。

        在 show() 之前调用（_present_dialog 的 before_present），窗口首帧
        即落在最终位置，避免 Windows 上"先显示默认位置再跳走"的两段式。
        """
        if self._positioned_away:
            return
        self._positioned_away = True
        parent = self.parentWidget()
        if parent is not None and parent.isVisible():
            self._move_away_from(parent.geometry())
            return
        if self.standalone:
            # 独立进程没有肥鱼窗口：改读配置目录 runtime 状态文件取肥鱼位置；
            # 读不到返回 None，保持默认位置（不许崩、也不许静默乱跳）。
            from .settings_standalone import standalone_pet_geometry

            pet_geo = standalone_pet_geometry(self.config)
            if pet_geo is not None:
                self._move_away_from(pet_geo)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().showEvent(event)
        # 兜底：未经 _present_dialog 直接 show 的路径仍要避让肥鱼
        self.move_away_from_pet()
        if not getattr(self, "_initial_focus_assigned", False):
            self._initial_focus_assigned = True
            self.sidebar.setFocus(Qt.FocusReason.OtherFocusReason)

    def _move_away_from(self, pet_geo: QRect) -> None:
        """首次显示时把窗口移到不与肥鱼相交的位置（右侧优先，再左侧/下方/上方）"""
        size = self.size()
        screen = self.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else QRect()
        for rect in (
            QRect(pet_geo.right() + 12, pet_geo.top(), size.width(), size.height()),
            QRect(pet_geo.left() - 12 - size.width(), pet_geo.top(), size.width(), size.height()),
            QRect(pet_geo.left(), pet_geo.bottom() + 12, size.width(), size.height()),
            QRect(pet_geo.left(), pet_geo.top() - 12 - size.height(), size.width(), size.height()),
        ):
            if avail.contains(rect):
                self.move(rect.topLeft())
                return

    def _page_shell(self, title: str, content: QWidget) -> QWidget:
        content_max_width = int(content.property("contentMaxWidth") or 960)
        page = _SettingsPageShell(content_max_width, self.pages)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 24, 28, 20)
        layout.setSpacing(12)
        heading_host = QWidget(page)
        heading_host.setObjectName("pageHeader")
        heading_host.setMaximumWidth(content_max_width)
        heading_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        heading_layout = QVBoxLayout(heading_host)
        heading_layout.setContentsMargins(0, 0, 0, 0)
        heading_layout.setSpacing(0)
        heading = QLabel(title, heading_host)
        heading.setObjectName("pageTitle")
        heading_layout.addWidget(heading)
        page.heading_host = heading_host
        layout.addWidget(heading_host, 0, Qt.AlignmentFlag.AlignHCenter)
        scroll = QScrollArea(page)
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        content.setMaximumWidth(content_max_width)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        return page

    def select_page(self, label: str) -> bool:
        """按侧栏标题选中页面，供右键菜单/更新通知做深链接。"""
        target = str(label or "").strip()
        for index in range(self.sidebar.count()):
            if self.sidebar.item(index).text() in (target, domain_label(target)):
                self.sidebar.setCurrentRow(index)
                return True
        return False

    def _add_page(self, label: str, icon_name: str, page: QWidget) -> None:
        item = QListWidgetItem(vector_widget_icon(self, icon_name, 16), label)
        item.setSizeHint(QSize(0, 38))
        self.sidebar.addItem(item)
        self.pages.addWidget(page)

    def _rebuild_domain_navigation(self) -> None:
        """Move existing rows into stable capability domains without cloning state."""
        old_pages = {self.sidebar.item(index).text(): self.pages.widget(index) for index in range(self.pages.count())}
        all_rows = list(self.findChildren(SettingRow))
        claimed: set[SettingRow] = set()

        def claim(*setting_ids: str) -> list[SettingRow]:
            rows = []
            for setting_id in setting_ids:
                row = self.findChild(SettingRow, f"settingRow_{setting_id}")
                if row is not None and row not in claimed:
                    claimed.add(row)
                    rows.append(row)
            return rows

        def claim_prefix(prefix: str) -> list[SettingRow]:
            rows = [row for row in all_rows if row.objectName().startswith(f"settingRow_{prefix}") and row not in claimed]
            claimed.update(rows)
            return rows

        def page_content(sections) -> QWidget:
            content = QWidget(self)
            layout = QVBoxLayout(content)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(18)
            for section in sections:
                title, rows, *options = section
                rows = [row for row in rows if row is not None]
                if rows:
                    layout.addWidget(
                        SettingsSection(
                            title,
                            rows,
                            content,
                            advanced=bool(options and options[0]),
                        )
                    )
            layout.addStretch(1)
            return content

        general = page_content(
            [
                (t("settings.dlg.language"), claim("ui_language")),
                (t("settings.dlg.startup"), claim("autostart")),
                (t("settings.dlg.window_system"), claim("dock_icon", "on_top", "auto_hide_fullscreen", "cursor_hidden_passthrough", "stream_capture", "tray_icon")),
                # 「多开」分组已随拓扑收口 Phase A 隐藏（见上方注释）
            ]
        )
        # 碰撞音效 2 行按 2026-09-17 定稿口径留在「肥鱼」：开关紧跟碰撞开关，
        # 音量随物理参数进「碰撞参数（高级）」。
        collision_primary = claim("collision_enabled", "collision_sound_enabled")
        collision_advanced = claim(
            "collision_restitution",
            "collision_friction",
            "collision_mass_scale",
            "collision_impulse_cap",
            "collision_sound_volume",
        )
        pet = page_content(
            [
                (t("settings.dlg.display"), claim("scale", "bubble_text_scale", "pet_opacity")),
                (t("settings.dlg.animation_movement"), claim("playback_speed", "animation_gap", "idle_low_fps", "no_move")),
                (t("settings.dlg.music"), claim("music_sing", "music_lyric", "music_lyric_lead", "music_browser_media")),
                (t("settings.dlg.drag_fling"), claim("drag_physics", "throw_strength", "slingshot_enabled", "lock_position", "shift_drag")),
                (t("settings.dlg.peek_from_edge"), claim("edge_probe")),
                (t("settings.dlg.spawn_little_fish"), claim("spawn_inherit_size", "spawn_smaller_than_main", "spawn_scale", "spawn_inherit_dynamic_island", "clear_spawned_pets")),
                (t("settings.dlg.multi_fish_collisions"), collision_primary),
                (t("settings.dlg.collision_parameters_advanced"), collision_advanced, True),
            ]
        )
        # 「互动」域（2026-09-22 分页）：整页在本模块构建（settings_interaction，
        # 行数预算原因），页内用任务标签分成「点击与音效 / 自言自语」两个同级任务；
        # 行不进 all_rows 快照，因此不需要 claim，也不会掉进「待分类（开发期）」。
        interaction = settings_interaction.build_interaction_domain(self)
        # 点击音效 4 行与 click_self_talk / click_balance / click_talk_bindings
        # 同享 click_ 前缀，按 2026-09-17 定稿口径整组留在 interaction 域。
        menu = SettingsTabContainer(self)
        menu.addTab(
            "layout",
            t("settings.dlg.menu_layout"),
            page_content(
                [
                    (t("settings.dlg.content_layout"), claim("menu_template", "context_menu_layout")),
                ]
            ),
        )
        menu.addTab(
            "launcher",
            t("settings.dlg.quick_launch"),
            page_content(
                [
                    (t("settings.dlg.configured_apps"), claim("quick_launch_apps")),
                ]
            ),
        )
        menu.addTab(
            "appearance",
            t("settings.dlg.appearance"),
            page_content(
                [
                    (t("settings.dlg.menu_appearance"), claim("menu_theme", "menu_density", "menu_radius", "menu_font", "menu_font_size", "menu_translucent", "menu_opacity")),
                    (
                        t("settings.dlg.advanced_colors"),
                        claim(
                            "light_background",
                            "light_foreground",
                            "light_hover",
                            "dark_background",
                            "dark_foreground",
                            "dark_hover",
                        ),
                        True,
                    ),
                    (t("settings.dlg.easter_egg_entry"), claim_prefix("egg_")),
                ]
            ),
        )
        menu.setProperty("contentMaxWidth", 1240)
        island_rows = list(old_pages.get(t("settings.dlg.dynamic_island"), QWidget()).findChildren(SettingRow))
        claimed.update(island_rows)
        desktop_components = page_content([(t("settings.dlg.desktop_capsule_dynamic_island"), island_rows)])

        ai_sections = None
        if self.ai_page is not None:
            appearance_rows = claim(
                "chat_ui_style", "chat_background", "chat_background_file", "chat_background_opacity", "chat_background_fill", "chat_bg_crops", "modern_chat_card_opacity"
            )
            ai_sections = page_content(
                [
                    (t("settings.dlg.api_list"), claim("provider_list")),
                    (
                        t("settings.dlg.model_connection"),
                        claim(
                            "provider_name",
                            "api_url",
                            "model",
                            "api_key",
                            "connection_test",
                        ),
                    ),
                    # 人设与「关于我」：全局一份、不随服务商切换，所以不放在「模型与连接」里；
                    # 紧跟一节默认收起的说明（设定在哪、怎么起作用、影响什么）。
                    (t("settings.ai.persona_section"), claim("system_prompt", "about_user")),
                    (t("settings.ai.persona_help"), claim("persona_help"), True),
                    (t("settings.dlg.system_notifications"), claim("system_notifications_enabled")),
                    (
                        t("settings.dlg.vision"),
                        claim(
                            "vision_same",
                            "vision_model",
                            "vision_url",
                            "vision_key",
                        ),
                    ),
                    (t("settings.dlg.connectors"), claim("github_connector", "github_token")),
                    (t("settings.dlg.knowledge_base"), claim_prefix("knowledge_base_")),
                    (
                        t("settings.dlg.generation_parameters_advanced"),
                        claim(
                            "timeout",
                            "temperature",
                            "max_tokens",
                            "effort",
                            "skip_ssl",
                        ),
                        True,
                    ),
                    (t("settings.dlg.chat_window"), appearance_rows),
                ]
            )
            ai_sections.setObjectName("settingsDomain_ai")
            # Keep the control owner alive for save/dependency behavior, but
            # visible rows now belong directly to the shared domain layout.
            self.ai_page.setParent(self)
            self.ai_page.hide()

        proactive_rows = list(old_pages.get(t("settings.dlg.screen_awareness"), QWidget()).findChildren(SettingRow))
        claimed.update(proactive_rows)
        voice_chime_rows = list(self.voice_chime_page.findChildren(SettingRow))
        claimed.update(voice_chime_rows)
        festival_rows = list(self.festival_page.findChildren(SettingRow))
        claimed.update(festival_rows)
        dialogue_rows = claim_prefix("dialogue_")
        automation = page_content(
            [
                (t("settings.dlg.do_reminders"), claim("todo_reminder_enabled", "todo_reminder_lead_minutes")),
                (t("settings.dlg.proactive_awareness"), proactive_rows),
            ]
        )
        # 「自定义台词」＝一个可折叠框（默认折叠）：逐事件文案行全部收进去，
        # 不用自定义台词的用户不该翻过整页文案框；搜索命中时会自动展开
        # （见 _search_settings）。全局风格控件（表达风格/专属文案对象/模板 JSON）
        # 不是事件文案，单独放「文案风格与模板」小节。
        phrases_box = CollapsibleGroup(t("settings.dlg.custom_lines_per_event"), automation)
        phrase_edit_keys = set(self.dialogue_phrase_edits)
        phrase_rows = [row for row in dialogue_rows
                       if row.objectName()[len("settingRow_dialogue_"):] in phrase_edit_keys]
        ungated_dialogue_rows = [row for row in dialogue_rows
                                 if row.objectName()[len("settingRow_dialogue_"):] not in phrase_edit_keys]
        if phrase_rows:
            phrases_box.add_group(t("settings.dlg.event_bubble_text"), phrase_rows)
        phrases_box.set_expanded(False)
        self.dialogue_phrases_box = phrases_box
        settings_pet_controls._apply_dialogue_mode_view(self)   # 内置模式 → 折叠框改名并只读显示那套台词
        automation_layout = automation.layout()
        # 「Agent 联动」＝两级结构：折叠框下按用途分子组（提示音效）。
        # 用现成的 CollapsibleGroup.add_group，不需要新造控件。
        agent_box = CollapsibleGroup(t("settings.dlg.agent_link"), automation)
        agent_box.add_group(t("settings.dlg.sounds"), claim_prefix("agent_sound_"))
        agent_box.set_expanded(True)
        self.agent_link_box = agent_box
        # 这些行已被上面的折叠框认领，必须登记，否则会再落进「待分类」。
        claimed.update(claim_prefix("agent_sound_"))
        # dialogue_* 里的全局风格控件（表达风格、专属文案对象、弹窗文案模板 JSON）
        # 不是某个事件的气泡文案，已被 claim_prefix("dialogue_") 认领（不再进
        # leftovers），若不显式放回本域就会从设置页里彻底消失。
        # 顶层顺序：「文案风格与模板」（全局风格控件）在前，自定义台词折叠框随后。
        insert_at = 0
        if ungated_dialogue_rows:
            automation_layout.insertWidget(
                insert_at,
                SettingsSection(t("settings.dlg.voice_style_templates"), ungated_dialogue_rows, automation),
            )
            insert_at += 1
            # 「这些台词怎么起作用」：固定台词模板 ≠ 对话人设；说明各自管哪些气泡、存在哪、留空时回退到什么
            self.bubble_style_help_section = settings_help.help_section(
                automation, "bubble_style_help", t("settings.dlg.bubble_style_help"),
                t("settings.dlg.bubble_style_help_hint"), t("settings.dlg.bubble_style_help_body"))
            automation_layout.insertWidget(insert_at, self.bubble_style_help_section)
            insert_at += 1
        automation_layout.insertWidget(insert_at, phrases_box)
        # 顶层顺序：Agent 联动 → VS Code 工作区 → 文案风格 → 自定义台词。
        # 必须在上面的插入全部做完之后再插，否则会被后来的 insertWidget(0, ...) 挤下去。
        # 「消费统计」（DeepSeek 余额差）2026-10-13 下线：Claude 没有余额接口，用量看灵动岛的「今日用量」
        automation_layout.insertWidget(0, agent_box)
        automation_layout.insertWidget(1, SettingsSection(t("settings.dlg.vs_code_workspaces"), settings_vscode.workspace_rows(self), automation))
        automation_layout.insertWidget(2, SettingsSection(t("settings.dlg.notification_center"), settings_notifications.notification_rows(self), automation))

        # 「简报与笔记」域（2026-10-24 用户要求放到第一层）：定时让 WSL 里的 Claude Code 替你读、写的东西
        # ——工作简报 / Slack 关注 / 工作笔记 / 个人助理（各带「这个功能怎么运作」）。
        briefing = page_content([])
        briefing_layout = briefing.layout()
        for index, widget in enumerate((
            settings_help.help_section(briefing, "briefing_page_help", t("settings.dlg.briefing_page_help"),
                                       t("settings.dlg.briefing_page_help_hint"), t("settings.dlg.briefing_page_help_body")),
            SettingsSection(settings_work_briefing.section_title(), settings_work_briefing.work_briefing_rows(self), briefing),
            settings_work_briefing.flow_section(self),
            SettingsSection(t("settings.dlg.slack_watch"), settings_slack_watch.slack_watch_rows(self), briefing),
            SettingsSection(settings_work_notes.section_title(), settings_work_notes.work_notes_rows(self), briefing),
            settings_work_notes.flow_section(self),
            SettingsSection(settings_personal.section_title(), settings_personal.personal_rows(self), briefing),
            settings_personal.flow_section(self),
        )):
            briefing_layout.insertWidget(index, widget)

        # 「语音」总域（2026-09-17 定稿口径）：只收鱼开口说话（TTS）类设置——
        # 语音报时整组 + 节日提醒 12 行（原「自动化与联动」域，带 speak/TTS 播报
        # 能力）。音效类回各自功能分组：点击音效 4 行回「互动 · 点击反馈」、
        # 碰撞音效 2 行回「肥鱼」碰撞组；Agent 提示音效（agent_sound_*）留在
        # Agent 联动折叠框内不动。
        voice = page_content(
            [
                (t("settings.dlg.spoken_time"), voice_chime_rows),
                (t("settings.dlg.festival_reminders"), festival_rows),
            ]
        )

        # 「文件识别」域（2026-09-19 新增）：拖文件解读的设置集中在此独立页。
        # 行在本模块构建（settings_file_interpret，行数预算原因），不走 claim。
        file_interpret = settings_file_interpret.build_file_interpret_page(self)

        # Preserve any newly added row until it receives an explicit domain decision.
        leftovers = [row for row in all_rows if row not in claimed and (self.ai_page is None or not self.ai_page.isAncestorOf(row))]
        if leftovers:
            layout = automation.layout()
            layout.insertWidget(max(0, layout.count() - 1), SettingsSection(t("settings.dlg.unsorted_development"), leftovers, automation))

        while self.pages.count():
            self.pages.removeWidget(self.pages.widget(0))
        self.sidebar.clear()
        domain_content = {
            "常规": general,
            "肥鱼": pet,
            "互动": interaction,
            "菜单": menu,
            "桌面组件": desktop_components,
            "AI 与对话": ai_sections,
            "简报与笔记": briefing,
            "自动化与联动": automation,
            "语音": voice,
            "文件识别": file_interpret,
        }
        for label, icon in SETTINGS_DOMAIN_NAV:
            content = domain_content.get(label)
            if content is None:
                continue
            self._add_page(domain_label(label), icon, self._page_shell(domain_label(label), content))
        for page in old_pages.values():
            page.deleteLater()

    def _clear_search_matches(self) -> None:
        for row in self._search_rows:
            if row.property("searchMatch"):
                row.setProperty("searchMatch", False)
                row.style().unpolish(row)
                row.style().polish(row)

    def _search_settings(self, query: str, *, advance: bool = False) -> None:
        query = query.strip().lower()
        self._clear_search_matches()
        if not query:
            self._search_matches = []
            self._search_index = -1
            self.search_status.hide()
            return
        matches = [row for row in self._search_rows if query in f"{row.label.text()} {row.hint_label.text()} {row.objectName()}".lower()]
        if not matches:
            self._search_matches = []
            self._search_index = -1
            self.search_status.setText(t("settings.dlg.no_matching_settings"))
            self.search_status.show()
            return
        if matches != self._search_matches:
            self._search_matches = matches
            self._search_index = 0
        elif advance:
            self._search_index = (self._search_index + 1) % len(matches)
        row = matches[self._search_index]
        row.setProperty("searchMatch", True)
        row.style().unpolish(row)
        row.style().polish(row)
        page_index = 0
        for index in range(self.pages.count()):
            if self.pages.widget(index).isAncestorOf(row):
                page_index = index
                break
        self.sidebar.setCurrentRow(page_index)
        page = self.pages.widget(page_index)
        ancestor = row.parentWidget()
        while ancestor is not None and ancestor is not page:
            if isinstance(ancestor, CollapsibleGroup):
                # 命中折叠框内的行：先自动展开，否则搜索结果存在但看不见。
                ancestor.set_expanded(True)
            if isinstance(ancestor, SettingsTabContainer):
                ancestor.activate_for_descendant(row)
                break
            ancestor = ancestor.parentWidget()
        scroll = page.findChild(QScrollArea, "settingsScroll")
        if scroll is not None:
            scroll.ensureWidgetVisible(row, 0, 24)
        self.search_status.setText(f"{self._search_index + 1}/{len(matches)} · {row.label.text()}")
        self.search_status.show()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self.search_edit and event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._search_settings(self.search_edit.text(), advance=True)
            return True
        return super().eventFilter(watched, event)

    def _apply_selected_theme(self, *_args) -> None:
        theme = str(self.menu_theme_select.currentData() or "system")
        dark = theme == "dark" or (theme == "system" and _system_dark())
        self.setProperty("settingsDark", dark)
        self.setStyleSheet(_settings_stylesheet(theme))
        for control in self.findChildren(ModernSelect):
            if control._popup is not None:
                control._popup.setStyleSheet(control.popupStyleSheet())
            control.update()
        for popup in self.findChildren(QMenu):
            if popup.property("settingsPopup"):
                configure_settings_action_popup(popup)
        for control in self.findChildren(ToggleSwitch):
            control.update()

    def _apply_autostart(self) -> None:
        """应用「开机自启」开关：仅在实际改动时写入系统登录项。

        保存按钮与直接关闭（X / Esc）共用，保证三条路径行为一致。
        """
        if self.autostart_check.isChecked() != self._autostart_initial:
            # set_enabled 返回 bool（enable()/disable()）；仅在明确失败时提示。
            ok = autostart_mod.set_enabled(self.autostart_check.isChecked())
            if ok is not False:
                # 已写入：之后再改回去要认这次的值（「保存」后窗口还开着）
                self._autostart_initial = self.autostart_check.isChecked()
            if ok is False:
                QMessageBox.warning(
                    self,
                    t("settings.dlg.couldn_t_set_start_at"),
                    t("settings.dlg.writing_start_at_sign_entry"),
                )

    def _save_only(self) -> None:
        """「保存」：写入配置但不关窗口（见 settings_save.save_without_exit）。"""
        settings_save.save_without_exit(self)

    def _save(self) -> None:
        """「保存并退出」：写入配置并关闭对话框。"""
        if not self._write_config():
            return
        self._saved_via_button = True
        self._apply_autostart()
        self.accept()

    def _write_config(self) -> bool:
        """把当前控件值写入 config 并落盘（按钮与直接关闭共用）。

        保存前从磁盘重读：吸收外部对本对话框未暴露字段的改动。
        standalone 下这条尤其关键——主进程在设置开着期间会自己写 config
        （托盘菜单开关等），不 reload 就把别人的改动回滚了。
        已知限制：已暴露字段仍是 last-writer-wins（对话框获胜）。
        返回是否成功落盘；失败时提示用户。
        """
        menu_layout_value = self.menu_layout_editor.value()
        menu_validation = resolve_menu_layout(
            menu_layout_value,
            registered_actions=MENU_ACTIONS.ids,
            available_actions=MENU_ACTIONS.ids,
        )
        if menu_validation.source == "fallback":
            QMessageBox.warning(
                self,
                t("settings.dlg.invalid_menu_layout"),
                t("settings.dlg.menu_layout_not_saved") + "、".join(menu_validation.diagnostics),
            )
            return False
        self.config.reload()
        minimum = min(self.min_spin.value(), self.max_spin.value())
        maximum = max(self.min_spin.value(), self.max_spin.value())
        texts = [line.strip()[:120] for line in self.texts_edit.toPlainText().splitlines() if line.strip()]
        self.config.set("scale", float(self.scale_combo.currentData()))
        self.config.set("spawn_inherit_size", self.spawn_inherit_size_check.isChecked())
        self.config.set("spawn_smaller_than_main", self.spawn_smaller_check.isChecked())
        self.config.set("spawn_scale", float(self.spawn_scale_combo.currentData()))
        self.config.set("spawn_inherit_dynamic_island", self.spawn_inherit_dynamic_island_check.isChecked())
        self.config.set("on_top", self.on_top_check.isChecked())
        if self.dock_icon_check is not None:
            self.config.set("show_dock_icon", self.dock_icon_check.isChecked())
        self.config.set("no_move", self.no_move_check.isChecked())
        self.config.set("mouse_through", self.mouse_through_check.isChecked())
        self.config.set("drag_physics", self.drag_physics_check.isChecked())
        self.config.set("throw_strength", str(self.throw_strength_select.currentData() or "standard"))
        self.config.set("slingshot_enabled", self.slingshot_check.isChecked())
        self.config.set("collision_enabled", self.collision_enabled_check.isChecked())
        self.config.set("collision_restitution", self.collision_restitution_spin.value())
        self.config.set("collision_friction", self.collision_friction_spin.value())
        self.config.set("collision_mass_scale", self.collision_mass_scale_spin.value())
        self.config.set("collision_impulse_cap", self.collision_impulse_cap_spin.value())
        self.config.set("collision_sound_enabled", self.collision_sound_check.isChecked())
        self.config.set("collision_sound_volume", float(self.collision_sound_volume_spin.value()) / 100.0)
        self.config.set("lock_position", self.lock_position_check.isChecked())
        self.config.set("shift_drag", self.shift_drag_check.isChecked())
        self.config.set("pet_opacity", int(self.pet_opacity_spin.value()))
        click_sound_enabled = self.click_sound_check.isChecked()
        click_sound_pack = self.click_sound_picker.value()
        click_sound_volume = float(self.click_sound_volume_spin.value()) / 100.0
        click_sound_pack_changed = self.config.get("click_sound_pack") != click_sound_pack
        click_sound_enabled_changed = self.config.get("click_sound_enabled") != click_sound_enabled
        self.config.set("click_sound_enabled", click_sound_enabled)
        self.config.set("click_sound_pack", click_sound_pack)
        self.config.set("click_sound_volume", click_sound_volume)
        # 只在真正需要时预热：点击音效处于启用状态，且本次写回改变了启用开关或音效包。
        # 音量变化/未改动不需要重建 QSoundEffect；开关从关到开已由勾选回调即时预热，
        # 因此普通“打开设置再关闭”不应在每次落盘都创建 QtMultimedia 音频对象。
        if click_sound_enabled and (click_sound_enabled_changed or click_sound_pack_changed):
            warm_click_sound_effects(
                click_sound_pack,
                data_dir=self.config.dir,
            )
        existing_island = self.config.get("dynamic_island", {})
        if not isinstance(existing_island, dict):
            existing_island = {}
        self.config.set(
            "dynamic_island",
            {
                "enabled": self.island_enabled_check.isChecked(),
                "show_icon": self.island_icon_check.isChecked(),
                "show_name": self.island_name_check.isChecked(),
                "show_info": self.island_info_check.isChecked(),
                "info_mode": str(self.island_info_mode_select.currentData() or "time"),
                "card_source": str(self.island_card_source_select.currentData() or "auto"),
                "show_status": self.island_status_check.isChecked(),
                "style": str(self.island_style_select.currentData() or "dark"),
                "opacity": float(self.island_opacity_spin.value()),
                "accent": str(self.island_accent_select.currentData() or "blue"),
                "icon": settings_island_icon.save_island_icon(self),
                "click_action": str(self.island_click_action_select.currentData() or "expand"),
                "hidden_chat": self.island_hidden_chat_check.isChecked(),
                "event_effects": self.island_event_effects_check.isChecked(),
                "edge_dock": self.island_edge_dock_check.isChecked(),
                "collision_enabled": self.island_collision_check.isChecked(),
                # 拖拽落点写入的停靠边与位置：设置页不回写，原样保留。
                "dock_edge": existing_island.get("dock_edge", "none"),
                "x": existing_island.get("x"),
                "y": existing_island.get("y"),
            },
        )
        self.config.set("click_show_self_talk", self.click_self_talk_check.isChecked())
        self.config.set("self_talk_speak_enabled", self.click_self_talk_speak_check.isChecked())
        self.config.set("self_talk_voice_precache_enabled",
                        self.self_talk_voice_precache_check.isChecked())
        self.config.set("music_sing_enabled", self.music_sing_check.isChecked())
        if getattr(self, "music_lyric_check", None) is not None:
            self.config.set("music_lyric_enabled", self.music_lyric_check.isChecked())
        if getattr(self, "music_lyric_lead_spin", None) is not None:
            self.config.set(
                "music_lyric_lead_seconds", float(self.music_lyric_lead_spin.value())
            )
        if getattr(self, "music_browser_media_check", None) is not None:
            self.config.set(
                "music_browser_media_enabled", self.music_browser_media_check.isChecked()
            )
        self.config.set("golden_spin_on_click", self.golden_spin_click_check.isChecked())
        self.config.set("golden_spin_direct", self.golden_spin_direct_check.isChecked())
        self.config.set("edge_probe_enabled", self.edge_probe_check.isChecked())
        if self.auto_hide_fullscreen_check is not None:
            self.config.set("auto_hide_fullscreen", self.auto_hide_fullscreen_check.isChecked())
        # 「单进程多开」键不落盘控件值：开关已隐藏（拓扑收口 Phase A），
        # 配置字典里加载的原值随 config.save() 原样回写（兼容保留）。
        if self.cursor_hidden_passthrough_check is not None:
            self.config.set("cursor_hidden_passthrough", self.cursor_hidden_passthrough_check.isChecked())
        if self.stream_capture_check is not None:
            self.config.set("stream_capture_mode", self.stream_capture_check.isChecked())
        self.config.set("playback_speed", float(self.speed_select.currentData()))
        self.config.set("animation_gap_seconds", self.gap_spin.value())
        self.config.set("idle_low_fps_enabled", self.idle_low_fps_check.isChecked())
        self.config.set("self_talk_enabled", self.self_talk_check.isChecked())
        self.config.set("self_talk_bubble_style", self.bubble_style_select.currentData())
        self.config.set("self_talk_min_interval", minimum)
        self.config.set("self_talk_max_interval", maximum)
        self.config.set("self_talk_duration_seconds", self.self_talk_duration_spin.value())
        self.config.set("self_talk_texts", texts or list(DEFAULT_SELF_TALK_TEXTS))
        self.config.set("self_talk_image_dir", self.self_talk_image_dir_picker.text())
        self.config.set("self_talk_image_scale", self.self_talk_image_scale_spin.value())
        self.config.set("self_talk_image_max_edge", self.self_talk_image_max_edge_spin.value())
        self.config.set("self_talk_image_chance", self.self_talk_image_chance_spin.value())
        self.config.set("bubble_text_scale", self.bubble_text_scale_spin.value())
        # Agent 联动：自定义 thinking 文案与音效（合并写回，不覆盖 agent_link 其他开关）
        self.config.set("dialogue_mode", str(self.dialogue_mode_select.currentData() or "legacy"))
        # 统一预设：编辑区当前层 flush 后，global 层 + agents delta 分层写回
        self._dialogue_flush_scope()
        new_global = self._dialogue_scope_values("")
        agents_delta: dict[str, dict[str, list[str]]] = {}
        for scope in self._dialogue_scope_buffer:
            if scope == "":
                continue
            values = self._dialogue_scope_values(str(scope))
            if values:
                agents_delta[str(scope)] = values
        # 兼容旧扁平存储：双层仅当存在 agents delta 或原配置已是双层时启用
        current_phrases = self.config.get("dialogue_phrases", {})
        was_preset = isinstance(current_phrases, dict) and ("global" in current_phrases or "agents" in current_phrases)
        if agents_delta or was_preset:
            self.config.set("dialogue_phrases", {"global": new_global, "agents": agents_delta})
        else:
            self.config.set("dialogue_phrases", new_global)
        # 记住上次编辑层：下次打开设置直接回到该 Agent 专属层（未知值回落全局）
        self.config.set("dialogue_last_scope", str(getattr(self, "_dialogue_scope", "") or ""))
        agent_cfg = dict(self.config.get("agent_link", {}))

        # Agent 联动音效写回
        agent_cfg["sound_enabled"] = self.agent_sound_check.isChecked()
        agent_cfg["sound_start_enabled"] = self.agent_sound_start_check.isChecked()
        agent_cfg["sound_start_path"] = self.agent_sound_start_picker.text().strip() or "builtin:agent-start"
        agent_cfg["sound_done_enabled"] = self.agent_sound_done_check.isChecked()
        agent_cfg["sound_done_path"] = self.agent_sound_done_picker.text().strip() or "builtin:agent-done"
        agent_cfg["sound_error_enabled"] = self.agent_sound_error_check.isChecked()
        agent_cfg["sound_error_path"] = self.agent_sound_error_picker.text().strip() or "builtin:agent-error"
        agent_cfg["sound_volume"] = float(self.agent_sound_volume_spin.value()) / 100.0
        agent_cfg["sound_cooldown_seconds"] = float(self.agent_sound_cooldown_spin.value())

        self.config.set("agent_link", agent_cfg)
        self.config.set("todo_reminder_enabled", self.todo_reminder_check.isChecked())
        self.config.set("todo_reminder_lead_minutes", int(self.todo_reminder_lead_spin.value()))
        # 语音报时设置页写回（仅写 voice_chime_* 11 键）
        if self.voice_chime_page is not None:
            self.voice_chime_page.apply_to_config()
        # 节日提醒设置页写回（仅写 festival_reminder_* / festival_custom_* 10 键）
        if self.festival_page is not None:
            self.festival_page.apply_to_config()
        self.config.set(
            "context_menu_appearance",
            {
                "theme": self.menu_theme_select.currentData(),
                "density": self.menu_density_select.currentData(),
                "corner_radius": self.menu_radius_select.currentData(),
                "ui_font": self.menu_font_select.currentData(),
                "ui_font_size": self.menu_font_size_select.currentData(),
                "translucent": self.menu_translucent_check.isChecked(),
                "opacity": self.menu_opacity_spin.value(),
                "light_background": self.light_background_picker.text(),
                "light_foreground": self.light_foreground_picker.text(),
                "light_hover": self.light_hover_picker.text(),
                "dark_background": self.dark_background_picker.text(),
                "dark_foreground": self.dark_foreground_picker.text(),
                "dark_hover": self.dark_hover_picker.text(),
            },
        )
        self.config.set("context_menu_template", self.menu_template_select.currentData())
        default_menu_nodes = load_default_menu_layout().get("nodes", [])
        self.config.set(
            "context_menu_layout",
            None if menu_layout_value.get("nodes") == default_menu_nodes else menu_layout_value,
        )
        self.config.set(
            "menu_easter_egg",
            {
                "enabled": self.egg_enabled_check.isChecked(),
                "title": self.egg_title_edit.text(),
                "hint": self.egg_hint_edit.text(),
                # 内置 assets 内的路径归一化回相对值，保持 portable（目录移动/自更新后仍可用）
                "avatar": store_fun_asset(self.egg_avatar_picker.text(), oijingjing_image_path()),
                "image_dir": store_fun_asset(self.egg_image_dir_picker.text(), oijingjing_image_path().parent),
            },
        )
        self.config.set("quick_launch_apps", self.quick_launch_editor.apps())
        if self.ai_page is not None:
            self.ai_page.save()
        settings_file_interpret.save_file_interpret_settings(self)
        settings_tray.save_tray_icon_setting(self)
        settings_language.save_language_setting(self)
        settings_vscode.save_workspace_settings(self)
        settings_notifications.save_notification_settings(self)
        settings_slack_watch.save_slack_watch_settings(self)
        settings_work_briefing.save_work_briefing_settings(self)
        settings_work_notes.save_work_notes_settings(self)
        settings_personal.save_personal_settings(self)
        if sys.platform == "win32" and self.include_ai and hasattr(self, "pro_enabled_check"):
            from .proactive import PRESET_DEFAULTS

            pro_data = dict(self.config.get("proactive_screen", {}) or {})
            preset = self.pro_preset_select.currentData()
            # 非 custom 预设下改了数值 → 自动落为 custom，否则运行时会被预设覆盖（gemini 审查发现）
            if preset in PRESET_DEFAULTS:
                pv = PRESET_DEFAULTS[preset]
                if (
                    self.pro_dwell_spin.value() != pv["dwell_seconds"]
                    or abs(self._pro_cooldown_minutes() - pv["cooldown_minutes"]) > 1e-6
                    or self.pro_cap_spin.value() != pv["daily_cap"]
                ):
                    preset = "custom"
            pro_data.update(
                {
                    "enabled": self.pro_enabled_check.isChecked(),
                    "dry_run": self.pro_dryrun_check.isChecked(),
                    "preset": preset,
                    "dwell_seconds": self.pro_dwell_spin.value(),
                    "cooldown_minutes": self._pro_cooldown_minutes(),
                    "min_request_interval_seconds": self.pro_min_interval_spin.value(),
                    "daily_cap": self.pro_cap_spin.value(),
                    "require_idle": self.pro_idle_check.isChecked(),
                    "min_idle_seconds": self.pro_idle_spin.value(),
                    "allow_when_mouse_through": self.pro_through_check.isChecked(),
                    "pre_cue": self.pro_precue_check.isChecked(),
                    "prefer_free_provider": self.pro_free_check.isChecked(),
                    "whitelist": [x.strip() for x in self.pro_whitelist_edit.toPlainText().splitlines() if x.strip()],
                }
            )
            self.config.set("proactive_screen", pro_data)
        self.config.set("autostart_wanted", self.autostart_check.isChecked())
        # 批 C：落种占位语义——仅当用户在该子肥鱼自己的设置界面保存过才置真；
        # 位置自动保存等一切后台写盘不得置位。主配置（slot 0/主肥鱼）保存不置位。
        if self.config.instance_id:
            self.config.set("user_customized", True)
        ok = self.config.save()
        if not ok:
            QMessageBox.warning(
                self,
                t("settings.dlg.save_failed"),
                t("settings.dlg.settings_couldn_t_written_disk") + str(self.config.path),
            )
        return ok

    def _on_voice_chime_preview(self, text: str) -> None:
        """语音报时设置页「试听」：透传父级 AppShell 的手动报时入口。

        父级（PetWindow / 对话框宿主）通过 on_voice_chime_now 暴露该能力；
        未接线时静默忽略（仅设置界面无副作用）。
        """
        if self.standalone:
            # 独立进程没有父级 AppShell：改走本地合成+播放通道（懒 import，
            # 启动路径不加载 voice_chime_service/edge-tts）。
            from .settings_standalone import preview_voice_chime

            preview_voice_chime(self, text)
            return
        cb = getattr(self.parent(), "on_voice_chime_now", None)
        if callable(cb):
            cb(text)

    def reject(self) -> None:  # noqa: N802 - Qt API
        """Esc 路径与关闭按钮一致：保存设置并应用开机自启。"""
        if not getattr(self, "_saved_via_button", False):
            try:
                self._write_config()
                self._apply_autostart()
            except Exception:
                logging.exception("Esc 关闭设置时保存配置失败")
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        """直接关闭（X / Esc）时同样落盘，避免修改丢失。

        设置项都是即时型偏好，与右键菜单/托盘修改的写入时机保持一致；
        已走「保存并退出」则跳过（防重复写入）。
        """
        if not getattr(self, "_saved_via_button", False):
            try:
                if not self._write_config():
                    event.ignore()
                    return
                self._apply_autostart()
            except Exception:
                logging.exception("关闭设置时保存配置失败")
        super().closeEvent(event)
