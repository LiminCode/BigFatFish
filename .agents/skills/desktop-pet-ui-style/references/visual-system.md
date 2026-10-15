# Desktop UI visual system

> 2026-10-14 起设置页改为 **Windows Phone / Metro** 风格（方角、磁贴、倾斜、上下折叠）。
> 下面的令牌以 `pet/settings_theme_qss.py::METRO_TOKENS` 与 `pet/settings_widgets.py` 的实现为准。

## Authority

Use these sources in descending order:

1. component behavior in `pet/settings_widgets.py` and QSS in `pet/settings_theme_qss.py` (`METRO_TOKENS`);
2. semantic vectors in `pet/context_menus/icons.py`;
3. accepted renders in `docs/screenshots/settings-redesign/iteration-10-metro-*`;
4. this summary.

When an accepted change intentionally alters a token, update this reference in the same change.

## Composition

```text
settings window
├── 200 px sidebar (one flat band; items are full-width tiles, selected = accent fill)
│   ├── save and exit
│   ├── search (square field)
│   └── stable capability domains
└── scrollable page shell
    ├── page title (large, light)
    └── section (18 px rhythm)
        ├── section title, or a tilting disclosure tile
        └── flat settings tile (no border, no shadow)
            ├── setting row
            ├── inset separator
            └── setting row
```

Keep the sidebar domains stable: 常规、桌宠、互动、菜单、桌面组件、AI 与对话、自动化与联动、语音、文件识别.
A platform changes availability inside a domain, not the domain list.

Peer tasks inside one domain (菜单: 菜单编排 / 快捷启动 / 外观; 互动: 点击与音效 / 自言自语) are a
**vertical accordion** (`SettingsTabContainer`): one tilting tile header per task, exactly one task open at a
time, the rest collapsed below. There are no horizontal tabs anywhere in the settings window.

## Typography

Use the Qt system general font ("Segoe UI" first on Windows). The window establishes 13 px body text.

| Role | Size | Weight | Color, light | Color, dark |
| --- | ---: | ---: | --- | --- |
| Page title | 30 px | 300 | `#111111` | `#f4f4f6` |
| Section title | 15 px | 600 | `#111111` | `#f4f4f6` |
| Disclosure / accordion tile | 14 px | 600 | `#111111` | `#f4f4f6` |
| Setting label | 13 px | 500 | `#1f1f1f` | `#e6e6ea` |
| Sidebar item | 14 px | 500 | `#1f1f1f` (selected `#ffffff`) | `#e6e6ea` (selected `#ffffff`) |
| Setting hint | 12 px | 400 | `#6d6d6d` | `#9a9aa3` |
| Search status | 11 px | regular | `#6d6d6d` | `#9a9aa3` |

Let labels and hints wrap. Increase row height from `sizeHint`; do not assign fixed text heights or shrink fonts.

## Layout and spacing

| Token | Value |
| --- | ---: |
| Minimum settings window | `720 × 500` |
| Sidebar width | `200` |
| Sidebar item height | `38` (left accent bar 4 px when selected) |
| Page shell margins | `30, 24, 28, 20` |
| Page section gap | `18` |
| Section title-to-tile gap | `7` |
| Accordion header-to-page gap | `6`; between tasks `8` extra |
| Setting row margins | `16, 10, 16, 10` |
| Tile separator inset | `16` per side |

At 720 px, preserve the sidebar and stack complex editors vertically. Controls stay reachable without
horizontal page scrolling. At standard/wide widths, let tiles fill the page.

## Surfaces and color

| Surface | Light | Dark |
| --- | --- | --- |
| Window/page | `#f2f2f2` | `#1b1b1f` |
| Sidebar band | `#e6e6e8` | `#141417` |
| Tile (card, disclosure header, menu, tree) | `#ffffff` | `#2a2a2f` |
| Tile hover | `#f7f7f7` | `#33333a` |
| Divider | `#ececec` | `#38383f` |
| Field | `#ffffff` / border `#b9b9b9` | `#26262b` / border `#4a4a54` |
| Button outline | `#333333` | `#e6e6e6` |
| Selected / accent | `#0a84ff` (white text) | `#0a84ff` (white text) |
| Search match | `#dcebff` | `#223a5c` |

**No rounded corners anywhere** (`border-radius: 0` on tiles, fields, buttons, menus, popups, scrollbars,
search, sidebar selection). Tiles have no border and no shadow. Buttons are 2 px outlined, transparent,
semibold; hover = tile hover fill, pressed = inverted (outline color fill, page-color text), focus = accent
outline. Disclosure / accordion headers are 44 px tiles with a 4 px accent left bar when expanded. The toggle
switch is a 44×20 rectangle: outlined track with a 12×20 knob, accent-filled when on.

## Tilt (Metro press feedback)

Every tile-like control tilts toward the pointer: `settings_widgets.tilt_transform` (±4° hover, ±8° pressed,
perspective distance 900 px). `TiltButton` (ordinary buttons, `SettingsMenuButton`, `SettingsDisclosureHeader`)
paints its QSS look on the tilted canvas; `TiltItemDelegate.install(view)` does the same for list items (the
sidebar). The transform is purely visual: hit testing, layout and geometry are unchanged, so it is interruptible
and leaves final geometry intact.

## Components

- `SettingRow` owns label, hint, accessibility relation, responsive copy, and right/stacked control placement.
- `ResponsiveActionRow` keeps a primary control and adjacent buttons inline when space permits, then moves actions below.
- `SettingsCard` owns the flat tile surface and inset separators.
- `SettingsSection` owns section rhythm. `advanced=True` is the only supported disclosure depth.
- `SettingsDisclosureHeader` (a `TiltButton`) owns the tile header look, the chevron (right when collapsed, down when expanded) and the accessible expanded/collapsed name.
- `SettingsTabContainer` is the vertical accordion for peer tasks inside one capability domain; it keeps the
  `addTab / keys / labels / currentKey / setCurrentKey / key_for_descendant / activate_for_descendant / stack`
  API so search deep links work unchanged.
- `ModernSelect`, `BrowserSpinBox`, and `BrowserDoubleSpinBox` own shared field geometry (square) and focus treatment.
- `TiltButton` / `TiltItemDelegate` own the tilt.
- `MenuLayoutEditor` and `QuickLaunchEditor` behave as before, on square panels.

Reuse these classes. A new control variant must define light/dark, hover, pressed, focus, disabled, and High DPI
behavior before adoption.

## Icons

Use `vector_widget_icon` and the semantic names in `pet/context_menus/icons.py`. Sidebar icons are 18 px monochrome
outlines; color follows the owning widget (white on the selected accent tile).

## State and motion

- User-hidden removes an item from runtime presentation but keeps its draft location.
- Platform-unavailable remains visible and explained in the editor, but is absent from runtime and preview.
- Disabled content keeps readable hierarchy at reduced contrast.
- Keyboard focus uses the accent outline and must remain visible on buttons, fields, selects, trees, and tile headers.
- The only motion is the pointer-driven tilt; settings forms do not animate routine row changes.

## Visual acceptance

Capture every affected settings domain at the top of its scroll view:

```bash
.venv/Scripts/python.exe scripts/capture_settings_pages.py   docs/screenshots/settings-redesign/<iteration> --width 1100 --height 760
```

Also capture 720 px for layout changes and `--dark` for color/surface changes. Inspect the images; file existence
alone is not acceptance. The offscreen platform has no CJK font, so text renders as boxes there — real-window
screenshots on the available desktop are the acceptance for typography.
