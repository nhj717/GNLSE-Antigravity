"""Cyberpunk Dark Theme and Color Palette for GNLSE Workstation.

Matching Google Stitch UI Blueprint:
- Background: #0f131d
- Surface container lowest: #0a0e18
- Surface container low: #171b26
- Surface container: #1c1f2a
- Surface container high: #262a35
- Surface container highest: #313540
- Surface bright: #353944
- Primary / Cyan accent: #00f5ff / #63f7ff / #e9feff
- Secondary / Pink accent: #ff4b89 / #ffb1c3
- Tertiary / Purple accent: #703eda / #e5d7ff
- Text on surface: #dfe2f1
- Text muted / variant: #b9caca
- Border / Outline: #3a494a
"""

from __future__ import annotations

# Color Palette Constants
BG_DARK = "#0f131d"
SURFACE_LOWEST = "#0a0e18"
SURFACE_LOW = "#171b26"
SURFACE = "#1c1f2a"
SURFACE_HIGH = "#262a35"
SURFACE_HIGHEST = "#313540"
SURFACE_BRIGHT = "#353944"

CYAN_ACCENT = "#00f5ff"
CYAN_BRIGHT = "#63f7ff"
CYAN_LIGHT = "#e9feff"
CYAN_DARK = "#003739"

PINK_ACCENT = "#ff4b89"
PINK_LIGHT = "#ffb1c3"
PINK_DARK = "#3f0019"

PURPLE_ACCENT = "#703eda"
PURPLE_LIGHT = "#e5d7ff"
PURPLE_DARK = "#23005c"

TEXT_PRIMARY = "#dfe2f1"
TEXT_MUTED = "#b9caca"
BORDER_COLOR = "#3a494a"
BORDER_SUBTLE = "#262a35"

GREEN_SUCCESS = "#00e676"
AMBER_WARNING = "#ffab00"
RED_ERROR = "#ff5252"

# Cyberpunk Master Stylesheet Generator
def build_cyberpunk_qss(colors: Optional[dict] = None) -> str:
    """Generate Cyberpunk QSS stylesheet with optional theme color overrides."""
    c = colors or {}
    bg_dark = c.get("bg_dark", BG_DARK)
    surface_lowest = c.get("surface_lowest", SURFACE_LOWEST)
    surface_low = c.get("surface_low", SURFACE_LOW)
    surface = c.get("surface", SURFACE)
    surface_high = c.get("surface_high", SURFACE_HIGH)
    surface_highest = c.get("surface_highest", SURFACE_HIGHEST)
    surface_bright = c.get("surface_bright", SURFACE_BRIGHT)
    cyan_accent = c.get("cyan_accent", CYAN_ACCENT)
    cyan_bright = c.get("cyan_bright", CYAN_BRIGHT)
    cyan_light = c.get("cyan_light", CYAN_LIGHT)
    cyan_dark = c.get("cyan_dark", CYAN_DARK)
    pink_accent = c.get("pink_accent", PINK_ACCENT)
    pink_light = c.get("pink_light", PINK_LIGHT)
    pink_dark = c.get("pink_dark", PINK_DARK)
    purple_accent = c.get("purple_accent", PURPLE_ACCENT)
    purple_light = c.get("purple_light", PURPLE_LIGHT)
    purple_dark = c.get("purple_dark", PURPLE_DARK)
    text_primary = c.get("text_primary", TEXT_PRIMARY)
    text_muted = c.get("text_muted", TEXT_MUTED)
    border_color = c.get("border_color", BORDER_COLOR)
    border_subtle = c.get("border_subtle", BORDER_SUBTLE)
    green_success = c.get("green_success", GREEN_SUCCESS)
    amber_warning = c.get("amber_warning", AMBER_WARNING)
    red_error = c.get("red_error", RED_ERROR)

    return f"""
/* Global Reset and Typography */
QWidget {{
    background-color: {bg_dark};
    color: {text_primary};
    font-family: 'JetBrains Mono', 'Space Grotesk', 'Segoe UI', 'DejaVu Sans', monospace, sans-serif;
    font-size: 11px;
    selection-background-color: {purple_accent};
    selection-color: #ffffff;
}}

QMainWindow {{
    background-color: {bg_dark};
}}

/* Scrollbars */
QScrollBar:vertical {{
    background: {surface_lowest};
    width: 10px;
    margin: 0px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical {{
    background: {surface_high};
    min-height: 20px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical:hover {{
    background: {cyan_accent};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: {surface_lowest};
    height: 10px;
    margin: 0px;
    border-radius: 5px;
}}
QScrollBar::handle:horizontal {{
    background: {surface_high};
    min-width: 20px;
    border-radius: 5px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {cyan_accent};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* Tabs (Cyberpunk Segmented Ribbon) */
QTabWidget::pane {{
    border: 1px solid {border_subtle};
    background-color: {bg_dark};
    border-radius: 6px;
    top: -1px;
}}
QTabBar::tab {{
    background-color: {surface_lowest};
    color: {text_muted};
    border: 1px solid {border_subtle};
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    padding: 7px 18px;
    margin-right: 2px;
    font-weight: 600;
    font-size: 11px;
}}
QTabBar::tab:selected {{
    background-color: {surface};
    color: {cyan_accent};
    border-top: 2px solid {cyan_accent};
    border-bottom: 1px solid {surface};
    font-weight: 700;
}}
QTabBar::tab:hover:!selected {{
    background-color: {surface_low};
    color: {text_primary};
}}

/* Push Buttons */
QPushButton {{
    background-color: {surface};
    color: {text_primary};
    border: 1px solid {border_subtle};
    border-radius: 4px;
    padding: 6px 12px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {surface_high};
    border-color: {border_color};
    color: {cyan_light};
}}
QPushButton:pressed {{
    background-color: {surface_lowest};
    border-color: {cyan_accent};
}}
QPushButton:disabled {{
    background-color: {surface_lowest};
    color: {text_muted};
    border-color: {border_subtle};
}}

/* Primary Action Buttons */
QPushButton#btn_primary {{
    background-color: {cyan_accent};
    color: {cyan_dark};
    font-weight: 700;
    border: none;
}}
QPushButton#btn_primary:hover {{
    background-color: {cyan_bright};
}}
QPushButton#btn_primary:pressed {{
    background-color: {cyan_light};
}}
QPushButton#btn_danger, QPushButton.danger {{
    background-color: {pink_accent};
    color: {pink_dark};
    border: 1px solid {pink_accent};
    font-weight: bold;
}}
QPushButton#btn_danger:hover, QPushButton.danger:hover {{
    background-color: {pink_light};
}}

/* Inputs (LineEdits, SpinBoxes) */
QLineEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {surface_lowest};
    color: {text_primary};
    border: 1px solid {border_subtle};
    border-radius: 4px;
    padding: 5px 8px;
    selection-background-color: {purple_accent};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1.5px solid {cyan_accent};
    background-color: {surface_low};
}}

/* ComboBoxes */
QComboBox {{
    background-color: {surface_lowest};
    color: {text_primary};
    border: 1px solid {border_subtle};
    border-radius: 4px;
    padding: 5px 8px;
    min-width: 80px;
}}
QComboBox:focus, QComboBox:on {{
    border: 1.5px solid {cyan_accent};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left: 1px solid {border_subtle};
}}
QComboBox QAbstractItemView {{
    background-color: {surface_low};
    color: {text_primary};
    selection-background-color: {purple_accent};
    selection-color: #ffffff;
    border: 1px solid {border_color};
    outline: none;
}}

/* CheckBoxes */
QCheckBox {{
    color: {text_primary};
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 3px;
    border: 1px solid {border_color};
    background-color: {surface_lowest};
}}
QCheckBox::indicator:hover {{
    border-color: {cyan_accent};
}}
QCheckBox::indicator:checked {{
    background-color: {cyan_accent};
    border-color: {cyan_accent};
    image: none;
}}

/* Group Boxes (Cyberpunk HUD Panels) */
QGroupBox {{
    font-weight: bold;
    border: 1px solid {border_subtle};
    border-radius: 6px;
    margin-top: 18px;
    padding-top: 12px;
    background-color: {surface_low};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    top: 0px;
    padding: 2px 8px;
    color: {cyan_accent};
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 0.5px;
    background-color: {surface_low};
    border-radius: 3px;
}}

/* Sliders */
QSlider::groove:horizontal {{
    height: 4px;
    background: {surface_high};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {cyan_accent};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {text_primary};
    border: 2px solid {cyan_accent};
    width: 14px;
    margin-top: -5px;
    margin-bottom: -5px;
    border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{
    background: {cyan_bright};
}}

/* Tables (Soliton Tracker & Audit) */
QTableWidget {{
    background-color: {surface_lowest};
    alternate-background-color: {surface_low};
    border: 1px solid {border_subtle};
    gridline-color: {border_subtle};
    color: {text_primary};
    selection-background-color: {purple_accent};
    selection-color: #ffffff;
    font-size: 10px;
}}
QHeaderView::section {{
    background-color: {surface};
    color: {cyan_accent};
    border: 1px solid {border_subtle};
    padding: 4px 6px;
    font-weight: bold;
    font-size: 10px;
    letter-spacing: 0.3px;
}}

/* Progress Bars */
QProgressBar {{
    background-color: {surface_lowest};
    border: 1px solid {border_subtle};
    border-radius: 4px;
    text-align: center;
    color: {text_primary};
    font-weight: bold;
    font-size: 10px;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {purple_accent}, stop:0.6 {cyan_accent}, stop:1 {cyan_bright});
    border-radius: 3px;
}}

/* Status Bar */
QStatusBar {{
    background-color: {surface_lowest};
    border-top: 1px solid {border_subtle};
    color: {text_muted};
    font-size: 10px;
}}
QStatusBar QLabel {{
    background-color: transparent;
    color: {text_muted};
}}

/* Splitters */
QSplitter::handle {{
    background-color: {border_subtle};
}}
QSplitter::handle:hover {{
    background-color: {cyan_accent};
}}
"""

CYBERPUNK_QSS = build_cyberpunk_qss()


def apply_cyberpunk_theme(target_widget, theme_dict: Optional[dict] = None) -> None:
    """Apply the Cyberpunk Dark theme to a QWidget or QApplication."""
    qss = build_cyberpunk_qss(theme_dict) if theme_dict else CYBERPUNK_QSS
    target_widget.setStyleSheet(qss)

