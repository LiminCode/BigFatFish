# -*- coding: utf-8 -*-
"""设置页「互动」域：页内任务标签（点击与音效 / 自言自语）+ 本域全部设置行。

**为什么单独一个模块**：``modern_settings_dialog.py`` 是"上帝对话框"（行数预算
反复触顶），本域的行定义与页装配搬到这里，收益是双向的——既让互动域长得像
「菜单」域那样可分页（主人反馈「单页面太多东西了」），又把 60+ 行从该文件搬出。

**为什么用页内标签而不是再拆一个侧栏域**：侧栏 9 个域是外部契约
（``SETTINGS_DOMAIN_NAV``，多处测试与截图脚本按索引/名称依赖）；同一个能力域内的
多个**同级任务**适合页内标签（先例：菜单域的 菜单编排 / 快捷启动 / 外观）。本域两个
标签就是两个同级任务：**点击与音效**（输入 + 点击反馈）、**自言自语**（周期气泡的
台词与配图）。

**接线契约**（与 ``settings_file_interpret`` 同口径）：

- 行在本模块构建、由 ``build_interaction_domain`` 挂进「互动」域；
- 行**不在** ``_rebuild_domain_navigation`` 开头的 ``all_rows`` 快照里，因此不需要
  ``claim``，也不会被判成「待分类（开发期）」；
- ``objectName`` 仍是 ``settingRow_<配置键>``，所以显隐联动（``_update_self_talk_controls``
  等按 objectName ``findChild``）与设置搜索索引照旧工作；
- 保存链一字不用改：``_write_config`` 全部基于控件属性。
"""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from .settings_widgets import SettingRow, SettingsSection, SettingsTabContainer
from .i18n import t

TAB_KEYS = ("click", "self_talk")
#: 页签显示名的文案键（用时 t()）；身份认 TAB_KEYS
TAB_LABELS = ("settings.interaction.tab_click", "settings.interaction.tab_self_talk")


def _page(dialog, title: str, sections: list[tuple[str, list[SettingRow]]]) -> QWidget:
    """标签页内容 = 若干 ``SettingsSection`` 竖排（与域页里的组渲染一致）。"""
    content = QWidget(dialog)
    layout = QVBoxLayout(content)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(18)
    for section_title, rows in sections:
        layout.addWidget(SettingsSection(section_title, rows, content))
    layout.addStretch(1)
    return content


def build_click_rows(dialog) -> list[SettingRow]:
    """「点击反馈」组的行（顺序与既有渲染顺序一致，多处用例按顺序/组名断言）。"""
    rows = [
        SettingRow("click_sound", t("settings.interaction.click_sound"), t("settings.interaction.play_light_feedback_sound_when"), dialog.click_sound_check),
        SettingRow("click_sound_pack", t("settings.interaction.sound_source"), t("settings.interaction.pick_preset_sound_pack_custom"), dialog.click_sound_picker, stacked=True),
        SettingRow("click_sound_volume", t("settings.interaction.sound_volume"), t("settings.interaction.volume_click_sound"), dialog.click_sound_volume_spin),
        SettingRow("click_sound_preview", t("settings.interaction.preview_sound"), t("settings.interaction.play_currently_selected_click_sound"), dialog.click_sound_preview_btn),
    ]
    rows.extend(
        [
            SettingRow("click_self_talk", t("settings.interaction.self_talk_click"), t("settings.interaction.show_random_self_talk_line"), dialog.click_self_talk_check),
            SettingRow(
                "click_self_talk_speak",
                t("settings.interaction.read_click_lines_aloud"),
                t("settings.interaction.when_click_triggers_self_talk"),
                dialog.click_self_talk_speak_check,
            ),
            SettingRow(
                "click_self_talk_precache",
                t("settings.interaction.pre_cache_lines"),
                t("settings.interaction.after_saving_synthesize_click_lines"),
                dialog.self_talk_voice_precache_check,
            ),
            SettingRow("click_talk_bindings", t("settings.interaction.lines_click_animations"), t("settings.interaction.give_each_click_animation_its"), dialog.click_talk_bindings_btn),
            SettingRow(
                "golden_spin_click",
                t("settings.interaction.golden_spin_click"),
                t("settings.interaction.when_clicking_fish_spins_360"),
                dialog.golden_spin_click_check,
            ),
            SettingRow(
                "golden_spin_direct",
                t("settings.interaction.spin_without_animation"),
                t("settings.interaction.when_click_starts_golden_spin"),
                dialog.golden_spin_direct_check,
                stacked=True,
            ),
        ]
    )
    return rows


def build_self_talk_rows(dialog) -> list[SettingRow]:
    """「自言自语」组的行（周期气泡的台词 / 节奏 / 配图）。"""
    return [
        SettingRow(
            "self_talk_bubble_style",
            t("settings.interaction.bubble_style"),
            t("settings.interaction.bubble_look_position_relative_fish"),
            dialog.bubble_style_select,
        ),
        SettingRow("self_talk", t("settings.interaction.bubble_self_talk"), t("settings.interaction.let_fish_show_random_thought"), dialog.self_talk_check),
        SettingRow("self_talk_duration", t("settings.interaction.display_time"), t("settings.interaction.how_long_each_text_image"), dialog.self_talk_duration_spin),
        SettingRow("self_talk_min", t("settings.interaction.shortest_gap"), t("settings.interaction.shortest_idle_time_between_one"), dialog.min_spin),
        SettingRow("self_talk_max", t("settings.interaction.longest_gap"), t("settings.interaction.longest_idle_time_between_one"), dialog.max_spin),
        SettingRow("self_talk_texts", t("settings.interaction.lines"), t("settings.interaction.one_per_line_leave_blank"), dialog.texts_edit, stacked=True),
        SettingRow(
            "self_talk_images",
            t("settings.interaction.image_folder"),
            t("settings.interaction.pick_at_random_from_common"),
            dialog.self_talk_image_dir_picker,
            stacked=True,
        ),
        SettingRow("self_talk_image_scale", t("settings.interaction.image_size"), t("settings.interaction.scale_images_animations_bubbles_relative"), dialog.self_talk_image_scale_spin),
        SettingRow(
            "self_talk_image_max_edge", t("settings.interaction.image_size_limit"),
            t("settings.interaction.largest_image_bubble_can_get"),
            dialog.self_talk_image_max_edge_spin,
        ),
        SettingRow(
            "self_talk_image_chance",
            t("settings.interaction.image_chance"),
            t("settings.interaction.chance_showing_image_click_timed"),
            dialog.self_talk_image_chance_spin,
        ),
    ]


def build_interaction_domain(dialog) -> QWidget:
    """「互动」域整页：一个页内任务标签容器（两个标签各含自己的组）。

    组名 ``输入`` / ``点击反馈`` / ``自言自语`` 保持不变——它们是对外契约，
    既有用例（test_menu_layout / test_desktop_pet_features / test_requested_regressions）
    按组名硬编码断言。
    """
    tabs = SettingsTabContainer(dialog)
    tabs.addTab(
        TAB_KEYS[0],
        t(TAB_LABELS[0]),
        _page(
            dialog,
            t(TAB_LABELS[0]),
            [
                (
                    t("settings.interaction.input"),
                    [
                        SettingRow(
                            "mouse_through",
                            t("settings.interaction.click_through"),
                            t("settings.interaction.when_fish_ignores_mouse_clicks"),
                            dialog.mouse_through_check,
                        )
                    ],
                ),
                (t("settings.interaction.click_feedback"), build_click_rows(dialog)),
            ],
        ),
    )
    tabs.addTab(
        TAB_KEYS[1],
        t(TAB_LABELS[1]),
        _page(dialog, t(TAB_LABELS[1]), [(t("settings.interaction.self_talk"), build_self_talk_rows(dialog))]),
    )
    return tabs
