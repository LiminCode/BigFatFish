# -*- coding: utf-8 -*-
"""语音报时设置页（现代设置对话框侧栏页）。

配置键（config.py 顶层平铺键）：
    voice_chime_enabled / voice_chime_schedule / voice_chime_custom_times /
    voice_chime_voice / voice_chime_rate / voice_chime_pitch / voice_chime_volume /
    voice_chime_show_bubble / voice_chime_show_quote /
    voice_chime_custom_quotes_zh / voice_chime_custom_quotes_en

台词/歌词按本地时间每 8 小时整体换一批（0-8 / 8-16 / 16-24 各对应库中一批，
跨周期切到新批次），同一周期内每次报时在批次内按顺序轮换取不同条目；自定义
台词非空时替换内置库参与同样的分批轮换，留空回退内置库。气泡报时文字以阿拉伯
数字展示（如“现在下午 15:45”），语音口播仍为中文数字。

自含 QWidget 页，
提供 apply_to_config，
由 modern_settings_dialog.py 注册为侧边栏「语音」总域下的「语音报时」分组并参与
_write_config 保存。
"""

from __future__ import annotations

import re

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .modern_settings_dialog import (
    BrowserSpinBox,
    SettingRow,
    SettingsSection,
    ToggleSwitch,
)
from .settings_widgets import ModernSelect
from .voice_chime import (
    DEFAULT_PITCH,
    DEFAULT_RATE,
    DEFAULT_SHOW_BUBBLE,
    DEFAULT_SHOW_QUOTE,
    DEFAULT_VOICE,
    DEFAULT_VOLUME,
    SCHEDULE_KEYS,
    SCHEDULE_LABELS,
    VOICE_OPTIONS,
    clean_pitch,
    clean_rate,
    clean_schedule,
    clean_voice,
    clean_volume,
)
from .i18n import maybe_t, t


def _sync_voice_select(select: ModernSelect, config) -> None:
    """按配置值刷新音色下拉：配置音色不在预设列表时追加一项并选中。

    配置值可能是手改的、也可能是**微软已经下架**的音色：显式标成「不在清单里」，
    别让用户以为它还是有效选项（服务层会自动改用默认音色并给一次提示）。
    """
    current = clean_voice(config.get("voice_chime_voice", DEFAULT_VOICE))
    if select.findData(current) < 0:
        select.addItem(t("settings.voice.not_list_current", current=current), current)
    select.setCurrentData(current)


class VoiceChimeSettingsPage(QWidget):
    """自含语音报时设置页。"""

    # 用户点击「试听」时发出（payload: 当前试听文案，空串表示按当前时间组装）
    preview_requested = Signal(str)

    def __init__(self, config, parent: QWidget | None = None):
        super().__init__(parent)
        self.config = config

        # ---- 基础设置 ----
        self.enabled_check = ToggleSwitch(self)
        self.enabled_check.setChecked(bool(self.config.get("voice_chime_enabled", False)))

        # ---- 调度 ----
        self.schedule_select = ModernSelect(self, width=170)
        for key in SCHEDULE_KEYS:
            self.schedule_select.addItem(maybe_t(f"settings.voice.schedule_{key}") if key in SCHEDULE_LABELS else key, key)
        self.schedule_select.setCurrentData(clean_schedule(self.config.get("voice_chime_schedule", "hourly")))

        self.custom_edit = QLineEdit(self)
        self.custom_edit.setText(str(self.config.get("voice_chime_custom_times", "") or ""))
        self.custom_edit.setPlaceholderText(t("settings.voice.e_g_08_30_12"))
        self.schedule_select.currentIndexChanged.connect(self._refresh_custom_enabled)

        # ---- 语音 ----
        self.voice_select = ModernSelect(self, width=230)
        for value, label in VOICE_OPTIONS:
            # 显示名跟随界面语言；VOICE_OPTIONS 里的中文是 zh 原文（也给服务层的提示用）
            label = maybe_t("settings.voice.option_" + re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")) or label
            self.voice_select.addItem(label, value)
        _sync_voice_select(self.voice_select, self.config)

        # 速率/音调/音量一律走纯逻辑层清洗：config.json 被手改成非法值时
        # 回落默认值，绝不让设置页在构造期抛异常把用户挡在设置界面之外。
        self.rate_spin = BrowserSpinBox(self)
        self.rate_spin.setRange(-100, 100)
        self.rate_spin.setSuffix(" %")
        self.rate_spin.setValue(clean_rate(self.config.get("voice_chime_rate", DEFAULT_RATE)))
        self.rate_spin.setToolTip(t("settings.voice.rate_offset_0_normal_positive"))

        self.pitch_spin = BrowserSpinBox(self)
        self.pitch_spin.setRange(-50, 50)
        self.pitch_spin.setSuffix(" Hz")
        self.pitch_spin.setValue(clean_pitch(self.config.get("voice_chime_pitch", DEFAULT_PITCH)))
        self.pitch_spin.setToolTip(t("settings.voice.pitch_offset_0_normal_positive"))

        self.volume_spin = BrowserSpinBox(self)
        self.volume_spin.setRange(0, 100)
        self.volume_spin.setSuffix(" %")
        self.volume_spin.setValue(clean_volume(self.config.get("voice_chime_volume", DEFAULT_VOLUME)))

        self.bubble_check = ToggleSwitch(self)
        self.bubble_check.setChecked(bool(self.config.get("voice_chime_show_bubble", DEFAULT_SHOW_BUBBLE)))

        self.quote_check = ToggleSwitch(self)
        self.quote_check.setChecked(bool(self.config.get("voice_chime_show_quote", DEFAULT_SHOW_QUOTE)))

        # ---- 自定义台词/歌词（一行一条；留空回退内置库）----
        self.custom_zh_edit = QPlainTextEdit(self)
        self.custom_zh_edit.setMinimumSize(280, 84)
        self.custom_zh_edit.setMaximumHeight(180)
        self.custom_zh_edit.setPlaceholderText(
            t("settings.voice.one_per_line_example_another")
        )
        self.custom_zh_edit.setPlainText(str(self.config.get("voice_chime_custom_quotes_zh", "") or ""))

        self.custom_en_edit = QPlainTextEdit(self)
        self.custom_en_edit.setMinimumSize(280, 84)
        self.custom_en_edit.setMaximumHeight(180)
        self.custom_en_edit.setPlaceholderText(
            "One quote per line, e.g.\nTake a short break and stretch.\nYou've got this!"
        )
        self.custom_en_edit.setPlainText(str(self.config.get("voice_chime_custom_quotes_en", "") or ""))

        self.preview_btn = QPushButton(t("settings.voice.preview_now"), self)
        self.preview_btn.setToolTip(t("settings.voice.speak_one_time_announcement_line"))
        self.preview_btn.clicked.connect(self._on_preview_clicked)

        # ---- Layout ----
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)

        root.addWidget(
            SettingsSection(
                t("settings.voice.basics"),
                [
                    SettingRow("voice_chime_enabled", t("settings.voice.enable_spoken_time"), t("settings.voice.when_time_announced_aloud_schedule"), self.enabled_check),
                    SettingRow("voice_chime_schedule", t("settings.voice.announcement_frequency"), t("settings.voice.hour_every_30_min_every"), self.schedule_select),
                    SettingRow("voice_chime_custom_times", t("settings.voice.custom_times"), t("settings.voice.only_used_custom_times_mode"), self.custom_edit),
                ],
                self,
            )
        )

        root.addWidget(
            SettingsSection(
                t("settings.voice.voice"),
                [
                    SettingRow(
                        "voice_chime_voice",
                        t("settings.voice.voice_2"),
                        t("settings.voice.built_chinese_english_voices_edge"),
                        self.voice_select,
                    ),
                    SettingRow("voice_chime_rate", t("settings.voice.rate"), t("settings.voice.speaking_rate_offset_percent_0"), self.rate_spin),
                    SettingRow("voice_chime_pitch", t("settings.voice.pitch"), t("settings.voice.pitch_offset_hz_0_normal"), self.pitch_spin),
                    SettingRow("voice_chime_volume", t("settings.voice.volume"), t("settings.voice.announcement_volume_0_100"), self.volume_spin),
                    SettingRow("voice_chime_show_bubble", t("settings.voice.announcement_bubble"), t("settings.voice.show_announcement_text_line_lyric"), self.bubble_check),
                    SettingRow("voice_chime_show_quote", t("settings.voice.lines_lyrics"), t("settings.voice.add_line_lyric_each_announcement"), self.quote_check),
                    SettingRow("voice_chime_preview", t("settings.voice.preview_now"), t("settings.voice.speak_one_time_announcement_line_2"), self.preview_btn),
                ],
                self,
            )
        )

        root.addWidget(
            SettingsSection(
                t("settings.voice.lines_lyrics"),
                [
                    SettingRow(
                        "voice_chime_custom_quotes_zh",
                        t("settings.voice.custom_lines_lyrics_chinese"),
                        t("settings.voice.one_per_line_if_filled"),
                        self.custom_zh_edit,
                        stacked=True,
                    ),
                    SettingRow(
                        "voice_chime_custom_quotes_en",
                        t("settings.voice.custom_lines_lyrics_english"),
                        t("settings.voice.one_per_line_same_rules"),
                        self.custom_en_edit,
                        stacked=True,
                    ),
                ],
                self,
            )
        )

        self._refresh_custom_enabled()

    # ------------------------------------------------------------ 交互
    def _on_preview_clicked(self) -> None:
        # 先落盘当前控件值，再发试听信号（服务端按最新配置合成播放）
        self.apply_to_config()
        self.preview_requested.emit("")

    def _refresh_custom_enabled(self) -> None:
        is_custom = self.schedule_select.currentData() == "custom"
        self.custom_edit.setEnabled(is_custom)

    # ------------------------------------------------------------ 配置读写
    def apply_to_config(self) -> None:
        """把控件值合并写回 config（仅写语音报时 11 键）。"""
        if self.config is None:
            return
        self.config.set("voice_chime_enabled", self.enabled_check.isChecked())
        self.config.set("voice_chime_schedule", self.schedule_select.currentData() or "hourly")
        self.config.set("voice_chime_custom_times", self.custom_edit.text().strip())
        self.config.set("voice_chime_voice", clean_voice(self.voice_select.currentData() or DEFAULT_VOICE))
        self.config.set("voice_chime_rate", self.rate_spin.value())
        self.config.set("voice_chime_pitch", self.pitch_spin.value())
        self.config.set("voice_chime_volume", self.volume_spin.value())
        self.config.set("voice_chime_show_bubble", self.bubble_check.isChecked())
        self.config.set("voice_chime_show_quote", self.quote_check.isChecked())
        self.config.set("voice_chime_custom_quotes_zh", self.custom_zh_edit.toPlainText().strip())
        self.config.set("voice_chime_custom_quotes_en", self.custom_en_edit.toPlainText().strip())
