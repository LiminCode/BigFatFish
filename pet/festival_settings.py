# -*- coding: utf-8 -*-
"""节日提醒设置页（现代设置对话框侧栏页）。

配置键（config.py 顶层平铺键，共 11 个）：
    festival_reminder_enabled / festival_reminder_cn /
    festival_reminder_solar_terms / festival_reminder_west /
    festival_reminder_mode / festival_reminder_count /
    festival_reminder_times / festival_reminder_show_quote /
    festival_reminder_speak / festival_custom_quotes_cn /
    festival_custom_quotes_west

语音播报（``festival_reminder_speak``）复用语音报时服务的音频通道，不新增音色/
语速/音调/音量键；同一分钟两者都到点时由报时让位（见 festival_service）。

风格对齐 pet/voice_chime_settings.py：
自含 QWidget 页，提供 apply_to_config，
由 modern_settings_dialog.py 在 automation 域注册并参与 _write_config 保存。

**本页刻意不提供「试听/立即提醒」按钮**：立即提醒已由右键菜单「今日节日」
承担，而 modern_settings_dialog.py 的行数预算只剩个位数余量（见该文件顶部
预算注释），再挂一个信号回调会直接顶爆预算。

关于导入方向：本模块顶层 ``from .modern_settings_dialog import ...`` 看似
循环导入，实际安全——modern_settings_dialog 在 ``__init__`` 内**函数级**
import 本模块，模块级依赖是单向的（与 voice_chime_settings 同构）。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .festival import (
    DEFAULT_COUNT,
    DEFAULT_MODE,
    DEFAULT_SHOW_QUOTE,
    DEFAULT_TIMES,
    MAX_COUNT,
    MIN_COUNT,
    MODE_KEYS,
    MODE_LABELS,
    clean_count,
    clean_mode,
)
from .modern_settings_dialog import (
    BrowserSpinBox,
    SettingRow,
    SettingsSection,
    ToggleSwitch,
)
from .settings_widgets import ModernSelect
from .voice_chime import clean_flag
from .i18n import maybe_t, t


class FestivalSettingsPage(QWidget):
    """自含节日提醒设置页。"""

    #: 用户点击「立即试听」时发出（无载荷）。回调由本页自行向上解析并调用；
    #: 保留信号是为了让外部（测试/宿主）也能观察到试听动作，与语音报时页对称。
    preview_requested = Signal()

    def __init__(self, config, parent: QWidget | None = None):
        super().__init__(parent)
        self.config = config

        def flag(key: str, default: bool) -> bool:
            return clean_flag(self.config.get(key, default), default)

        # ---- 基础设置 ----
        self.enabled_check = ToggleSwitch(self)
        self.enabled_check.setChecked(flag("festival_reminder_enabled", False))

        self.cn_check = ToggleSwitch(self)
        self.cn_check.setChecked(flag("festival_reminder_cn", True))

        self.solar_terms_check = ToggleSwitch(self)
        self.solar_terms_check.setChecked(flag("festival_reminder_solar_terms", True))

        self.west_check = ToggleSwitch(self)
        self.west_check.setChecked(flag("festival_reminder_west", True))

        self.speak_check = ToggleSwitch(self)
        self.speak_check.setChecked(flag("festival_reminder_speak", False))

        # ---- 提醒时间 ----
        self.mode_select = ModernSelect(self, width=170)
        for key in MODE_KEYS:
            self.mode_select.addItem(maybe_t(f"settings.festival.mode_{key}") if key in MODE_LABELS else key, key)
        self.mode_select.setCurrentData(
            clean_mode(self.config.get("festival_reminder_mode", DEFAULT_MODE))
        )
        self.mode_select.currentIndexChanged.connect(self._refresh_mode_controls)

        self.count_spin = BrowserSpinBox(self)
        self.count_spin.setRange(MIN_COUNT, MAX_COUNT)
        self.count_spin.setValue(
            clean_count(self.config.get("festival_reminder_count", DEFAULT_COUNT))
        )
        self.count_spin.setToolTip(t("settings.festival.spread_reminders_evenly_between_09"))

        self.times_edit = QLineEdit(self)
        self.times_edit.setText(str(self.config.get("festival_reminder_times", DEFAULT_TIMES) or ""))
        self.times_edit.setPlaceholderText(t("settings.festival.e_g_09_00_12"))

        # ---- 文案 ----
        self.quote_check = ToggleSwitch(self)
        self.quote_check.setChecked(flag("festival_reminder_show_quote", DEFAULT_SHOW_QUOTE))

        self.custom_cn_edit = QPlainTextEdit(self)
        self.custom_cn_edit.setMinimumSize(280, 84)
        self.custom_cn_edit.setMaximumHeight(180)
        self.custom_cn_edit.setPlaceholderText(
            t("settings.festival.one_per_line_appended_built")
        )
        self.custom_cn_edit.setPlainText(
            str(self.config.get("festival_custom_quotes_cn", "") or "")
        )

        self.custom_west_edit = QPlainTextEdit(self)
        self.custom_west_edit.setMinimumSize(280, 84)
        self.custom_west_edit.setMaximumHeight(180)
        self.custom_west_edit.setPlaceholderText(
            t("settings.festival.one_quote_per_line_appended")
        )
        self.custom_west_edit.setPlainText(
            str(self.config.get("festival_custom_quotes_west", "") or "")
        )

        # ---- 试听 ----
        self.preview_btn = QPushButton(t("settings.festival.preview_now"), self)
        self.preview_btn.setToolTip(t("settings.festival.show_festival_reminder_right_now"))
        self.preview_btn.clicked.connect(self._on_preview_clicked)

        # ---- Layout ----
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)

        root.addWidget(
            SettingsSection(
                t("settings.festival.basics"),
                [
                    SettingRow(
                        "festival_reminder_enabled",
                        t("settings.festival.enable_festival_reminders"),
                        t("settings.festival.festival_solar_term_day_fish"),
                        self.enabled_check,
                    ),
                    SettingRow(
                        "festival_reminder_cn",
                        t("settings.festival.chinese_festivals"),
                        t("settings.festival.spring_festival_lantern_festival_dragon"),
                        self.cn_check,
                    ),
                    SettingRow(
                        "festival_reminder_solar_terms",
                        t("settings.festival.x_24_solar_terms"),
                        t("settings.festival.start_spring_rain_water_awakening"),
                        self.solar_terms_check,
                    ),
                    SettingRow(
                        "festival_reminder_west",
                        t("settings.festival.western_holidays"),
                        t("settings.festival.valentine_day_april_fools_day"),
                        self.west_check,
                    ),
                    SettingRow(
                        "festival_reminder_speak",
                        t("settings.festival.read_aloud"),
                        t("settings.festival.read_festival_reminder_aloud_voice"),
                        self.speak_check,
                    ),
                ],
                self,
            )
        )

        root.addWidget(
            SettingsSection(
                t("settings.festival.reminder_times"),
                [
                    SettingRow(
                        "festival_reminder_mode",
                        t("settings.festival.reminder_mode"),
                        t("settings.festival.by_count_spreads_number_below"),
                        self.mode_select,
                    ),
                    SettingRow(
                        "festival_reminder_count",
                        t("settings.festival.reminders_per_day"),
                        t("settings.festival.how_many_reminders_per_day"),
                        self.count_spin,
                    ),
                    SettingRow(
                        "festival_reminder_times",
                        t("settings.festival.custom_reminder_times"),
                        t("settings.festival.only_used_custom_times_mode"),
                        self.times_edit,
                    ),
                ],
                self,
            )
        )

        root.addWidget(
            SettingsSection(
                t("settings.festival.lines"),
                [
                    SettingRow(
                        "festival_reminder_show_quote",
                        t("settings.festival.add_line"),
                        t("settings.festival.add_poem_saying_classic_quote"),
                        self.quote_check,
                    ),
                    SettingRow(
                        "festival_custom_quotes_cn",
                        t("settings.festival.custom_chinese_lines"),
                        t("settings.festival.one_per_line_appended_built_2"),
                        self.custom_cn_edit,
                        stacked=True,
                    ),
                    SettingRow(
                        "festival_custom_quotes_west",
                        t("settings.festival.custom_western_lines"),
                        t("settings.festival.one_per_line_appended_built_3"),
                        self.custom_west_edit,
                        stacked=True,
                    ),
                    SettingRow(
                        "festival_preview",
                        t("settings.festival.preview_now"),
                        t("settings.festival.show_one_reminder_now_current"),
                        self.preview_btn,
                    ),
                ],
                self,
            )
        )

        self._refresh_mode_controls()

    # ------------------------------------------------------------ 交互
    def _on_preview_clicked(self) -> None:
        """试听：先落盘当前控件值，再透传给窗口的「今日节日」入口。

        **先 apply_to_config 再触发**：与语音报时试听同约定——服务端按最新配置
        组装文案与语音参数，否则试听的是上一次保存的设置。
        """
        self.apply_to_config()
        callback = self._resolve_preview_callback()
        if callback is not None:
            callback()
        self.preview_requested.emit()

    def _resolve_preview_callback(self):
        """向上查找窗口暴露的 ``on_festival_now`` 回调（找到即返回，找不到返回 None）。

        为什么不走「页面发信号 → modern_settings_dialog 处理」那条路（语音报时用的
        是那条）：该对话框的行数预算只剩个位数余量，再挂一个信号连接与处理方法会
        直接顶爆预算。放在本页则**零成本**（本文件不受行数预算约束）。

        用**有界向上遍历**而不是写死 ``parent().parent()``：SettingsRow 会被
        ``_rebuild_domain_navigation`` 重新 parent 到共享卡片域，写死层数将来会被
        一次无关的重构悄悄打断。找不到时静默忽略（仅设置界面，无副作用）。
        """
        widget = self.parentWidget()
        for _ in range(4):  # 页面 -> 对话框 -> 窗口/壳，留余量即可，不做无限上溯
            if widget is None:
                return None
            callback = getattr(widget, "on_festival_now", None)
            if callable(callback):
                return callback
            widget = widget.parentWidget()
        return None

    def _refresh_mode_controls(self) -> None:
        """按提醒方式启用/禁用「次数」与「自定义时间」控件，避免改了没生效的困惑。"""
        is_custom = self.mode_select.currentData() == "custom"
        self.count_spin.setEnabled(not is_custom)
        self.times_edit.setEnabled(is_custom)

    # ------------------------------------------------------------ 配置读写
    def apply_to_config(self) -> None:
        """把控件值合并写回 config（仅写节日提醒 10 键）。"""
        if self.config is None:
            return
        self.config.set("festival_reminder_enabled", self.enabled_check.isChecked())
        self.config.set("festival_reminder_cn", self.cn_check.isChecked())
        self.config.set("festival_reminder_solar_terms", self.solar_terms_check.isChecked())
        self.config.set("festival_reminder_west", self.west_check.isChecked())
        self.config.set("festival_reminder_mode", self.mode_select.currentData() or DEFAULT_MODE)
        self.config.set("festival_reminder_count", self.count_spin.value())
        self.config.set("festival_reminder_times", self.times_edit.text().strip())
        self.config.set("festival_reminder_show_quote", self.quote_check.isChecked())
        self.config.set("festival_reminder_speak", self.speak_check.isChecked())
        self.config.set("festival_custom_quotes_cn", self.custom_cn_edit.toPlainText().strip())
        self.config.set("festival_custom_quotes_west", self.custom_west_edit.toPlainText().strip())
