# -*- coding: utf-8 -*-
"""设置页主题 QSS（2026-10-14 起：Windows Phone / Metro 风格）。

几条口径（和 ``.agents/skills/desktop-pet-ui-style/references/visual-system.md`` 同步）：

- **方角**：卡片、字段、按钮、菜单、侧栏选中态、搜索框一律 ``border-radius: 0``。
- **磁贴**：卡片是平铺在底色上的一块「磁贴」——没有描边、没有阴影，靠底色深浅分层；
  可点的磁贴（折叠表头、按钮、侧栏项）会朝光标倾斜（见 ``settings_widgets.TiltButton``）。
- **大而轻的标题**：页标题 30px / 细体；节标题 15px / 半粗。
- **按钮**：2px 描边、透明底、粗体字；悬停浅底，按下反色，焦点主题色描边。
- **侧栏**：整条一块深一点的带子，项是满宽的平铺条，选中 = 主题色底白字。
- 主题色仍是 ``#0a84ff``，只给选中 / 焦点 / 打开的开关 / 折叠表头的左缘。

``_system_dark`` / ``BROWSER_CONTROL_STYLESHEET`` 在 settings_widgets 中定义。
"""
from __future__ import annotations

from .settings_widgets import _system_dark, BROWSER_CONTROL_STYLESHEET

#: 设置页的颜色令牌（明 / 暗）。测试按这张表核对 QSS 里的值。
METRO_TOKENS = {
    "light": {
        "page": "#f2f2f2", "sidebar": "#e6e6e8", "tile": "#ffffff", "tile_hover": "#f7f7f7", "divider": "#ececec",
        "title": "#111111", "text": "#1f1f1f", "muted": "#6d6d6d", "disabled": "#a8a8a8",
        "outline": "#333333", "selected": "#0a84ff", "selected_text": "#ffffff", "accent": "#0a84ff",
        "field": "#ffffff", "field_border": "#b9b9b9", "match": "#dcebff",
    },
    "dark": {
        "page": "#1b1b1f", "sidebar": "#141417", "tile": "#2a2a2f", "tile_hover": "#33333a", "divider": "#38383f",
        "title": "#f4f4f6", "text": "#e6e6ea", "muted": "#9a9aa3", "disabled": "#6a6a72",
        "outline": "#e6e6e6", "selected": "#0a84ff", "selected_text": "#ffffff", "accent": "#0a84ff",
        "field": "#26262b", "field_border": "#4a4a54", "match": "#223a5c",
    },
}

_TEMPLATE = """
QDialog {{
    background: {page};
    color: {text};
    font-family: "Segoe UI", "SF Pro Text", ".AppleSystemUIFont", "PingFang SC", "Microsoft YaHei UI", sans-serif;
    font-size: 13px;
}}
QFrame#sidebarPane {{ background: {sidebar}; border: none; }}
QStackedWidget {{ background: {page}; }}
QWidget#aiSettingsContent {{ background: transparent; }}
QLineEdit#settingsSearch {{
    min-height: 30px;
    padding: 0 8px;
    background: {field};
    color: {text};
    border: 2px solid transparent;
    border-radius: 0;
}}
QLineEdit#settingsSearch:focus {{ border: 2px solid {accent}; }}
QPushButton#saveAndExit, QPushButton#saveOnly {{
    min-height: 30px;
    padding: 2px 10px;
    text-align: left;
    background: transparent;
    border: none;
    border-radius: 0;
    color: {text};
    font-weight: 600;
}}
QPushButton#saveAndExit:hover, QPushButton#saveOnly:hover {{ background: {tile_hover}; }}
QPushButton#saveAndExit:pressed, QPushButton#saveOnly:pressed {{ background: {selected}; color: {selected_text}; }}
QLabel#searchStatus {{ padding: 0 5px; color: {muted}; font-size: 11px; }}
QListWidget#settingsSidebar {{
    background: transparent;
    border: none;
    outline: none;
    font-size: 14px;
    font-weight: 500;
}}
QListWidget#settingsSidebar::item {{
    min-height: 34px;
    padding: 4px 12px;
    border-radius: 0;
    border-left: 4px solid transparent;
    color: {text};
}}
QListWidget#settingsSidebar::item:hover {{ background: {tile}; }}
QListWidget#settingsSidebar::item:selected {{
    background: {selected};
    border-left: 4px solid {selected};
    color: {selected_text};
}}
QLabel#pageTitle {{
    font-size: 30px;
    font-weight: 300;
    color: {title};
}}
QLabel#sectionTitle {{
    font-size: 15px;
    font-weight: 600;
    color: {title};
}}
QFrame#settingsCard {{ background: {tile}; border: none; border-radius: 0; }}
QFrame#cardSeparator {{ background: {divider}; border: none; margin-left: 16px; margin-right: 16px; }}
QLabel#settingLabel {{ font-size: 13px; font-weight: 500; color: {text}; }}
QLabel#settingHint {{ font-size: 12px; font-weight: 400; color: {muted}; }}
QLabel#settingLabel:disabled, QLabel#settingHint:disabled {{ color: {disabled}; }}
SettingRow[searchMatch="true"] {{ background: {match}; border-radius: 0; }}
QScrollArea#settingsScroll, QScrollArea#settingsScroll > QWidget > QWidget {{ background: transparent; }}
QLabel#quickLaunchCount, QLabel#menuLayoutEditorLabel, QLabel#menuLayoutPreviewLabel, QLabel#menuLayoutEditorHint {{
    color: {muted};
    font-size: 12px;
    font-weight: 500;
    padding-left: 2px;
}}
QLabel#quickLaunchName {{ color: {text}; font-size: 13px; font-weight: 500; }}
QLabel#quickLaunchDetail {{ color: {muted}; font-size: 11px; }}
QLabel#quickLaunchEmpty {{ color: {muted}; background: {page}; border: 2px dashed {field_border}; border-radius: 0; }}
QListWidget#quickLaunchList {{ background: {page}; border: none; border-radius: 0; outline: none; padding: 3px; }}
QListWidget#quickLaunchList::item {{ min-height: 30px; padding: 3px 7px; border-radius: 0; }}
QListWidget#quickLaunchList::item:selected {{ background: {selected}; color: {selected_text}; }}
QLabel#menuLayoutEditorHint {{ font-weight: 400; }}
QFrame#menuLayoutEditorPanel, QFrame#menuLayoutPreviewPanel {{ background: {page}; border: none; border-radius: 0; }}
QFrame#imagePreviewDrawer {{ background: {tile}; border: none; border-left: 1px solid {divider}; }}
QScrollArea#imagePreviewScroll, QScrollArea#imagePreviewScroll > QWidget > QWidget, QWidget#imageMasonryFlow {{
    background: transparent;
}}
QLabel#imagePreviewTitle {{ color: {title}; font-size: 18px; font-weight: 300; }}
QLabel#imagePreviewCount, QLabel#imagePreviewPath {{ color: {muted}; font-size: 11px; }}
QLabel#imagePreviewEmpty {{ color: {muted}; }}
QPushButton#imagePreviewClose {{ background: transparent; border: none; font-size: 20px; }}
QPushButton#imagePreviewClose:hover {{ background: {tile_hover}; }}
QTreeWidget#menuLayoutTree, QTreeWidget#menuLayoutPreview {{
    background: {tile};
    border: none;
    border-radius: 0;
    outline: none;
    padding: 4px;
}}
QTreeWidget#menuLayoutTree::item, QTreeWidget#menuLayoutPreview::item {{
    min-height: 28px;
    padding: 1px 5px;
    border-radius: 0;
}}
QTreeWidget#menuLayoutTree::item:hover {{ background: {tile_hover}; }}
QTreeWidget#menuLayoutTree::item:selected {{ background: {selected}; color: {selected_text}; }}
QTreeWidget#menuLayoutPreview::item:hover {{ background: transparent; }}
QTreeWidget#menuLayoutTree QHeaderView::section {{
    min-height: 28px;
    padding: 0 8px;
    background: {page};
    border: none;
    border-bottom: 2px solid {divider};
    color: {muted};
    font-size: 12px;
    font-weight: 600;
}}
QMenu {{
    background: {tile};
    color: {text};
    border: 1px solid {field_border};
    border-radius: 0;
    padding: 4px;
}}
QMenu::item {{ min-height: 26px; padding: 2px 24px 2px 10px; border-radius: 0; }}
QMenu::item:selected {{ background: {selected}; color: {selected_text}; }}
QMenu::item:disabled {{ color: {disabled}; }}
QPushButton {{
    min-height: 26px;
    padding: 1px 14px;
    background: transparent;
    border: 2px solid {outline};
    border-radius: 0;
    color: {text};
    font-weight: 600;
}}
QPushButton:hover {{ background: {tile_hover}; }}
QPushButton:pressed {{ background: {outline}; color: {page}; }}
QPushButton:focus {{ border: 2px solid {accent}; }}
QPushButton:disabled {{ border-color: {disabled}; color: {disabled}; }}
QPushButton[settingsMenuButton="true"] {{ padding-right: 26px; text-align: left; }}
QPushButton#advancedSectionToggle {{
    min-height: 44px;
    padding: 0 40px 0 14px;
    text-align: left;
    background: {tile};
    border: none;
    border-left: 4px solid transparent;
    border-radius: 0;
    color: {title};
    font-size: 14px;
    font-weight: 600;
}}
QPushButton#advancedSectionToggle:hover {{ background: {tile_hover}; }}
QPushButton#advancedSectionToggle:checked {{ border-left: 4px solid {accent}; }}
QPushButton#advancedSectionToggle:pressed {{ background: {tile_hover}; color: {title}; }}
QPushButton#advancedSectionToggle:focus {{ border: 2px solid {accent}; border-left: 4px solid {accent}; }}
QSplitter::handle {{ background: transparent; }}
QToolButton {{ color: {text}; }}
QCheckBox, QRadioButton, QComboBox, QListWidget, QTreeWidget, QTableView {{ color: {text}; }}
"""

_DARK_BROWSER_OVERRIDE = """
QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
    background: #26262b; color: #e6e6ea; border: 1px solid #4a4a54;
}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QPlainTextEdit:hover { border-color: #5c5c66; }
QSpinBox::up-button, QDoubleSpinBox::up-button { border-left: 1px solid #4a4a54; border-bottom: 1px solid #4a4a54; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: #55555e; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: #6a6a74; }
"""


def metro_stylesheet(dark: bool) -> str:
    """只有设置页自己的那一段（不含共享字段控件）。"""
    return _TEMPLATE.format(**METRO_TOKENS["dark" if dark else "light"])


def _settings_stylesheet(theme: str = "system") -> str:
    """Metro 主题 + 共享字段控件样式；深色系统时追加深色字段覆盖段。"""
    dark = theme == "dark" or (theme == "system" and _system_dark())
    sheet = metro_stylesheet(dark) + BROWSER_CONTROL_STYLESHEET
    return sheet + _DARK_BROWSER_OVERRIDE if dark else sheet


# 兼容：旧名字仍可 import（有用例按它找浅色表）
_LIGHT_SETTINGS_STYLESHEET = metro_stylesheet(False)
_DARK_OVERRIDE = metro_stylesheet(True)
