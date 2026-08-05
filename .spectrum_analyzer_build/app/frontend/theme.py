"""
theme.py
--------
Application-scope theming helpers.

Two responsibilities:

1. install_dark_palette()
   Forces the Fusion style and a fully dark QPalette on the QApplication.
   This is the layer that QSS cannot reach: native window frames, floating
   QDockWidget top-levels, QMenu/QComboBox popups, scroll areas, and the
   arrow primitives QStyle draws inside QSpinBox sub-controls. Without it,
   any widget that becomes its own top-level window falls back to the OS
   light palette -- which is the white background seen on popped-out docks.

2. DOCK_QSS_PATCH
   Additive rules appended to the existing MainWindow sheet. Nothing here
   overrides an existing rule; it only fills gaps (dock shell backgrounds,
   custom title bar, spin-button geometry).

Owner: Developer B (Frontend/GUI)
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication


# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------
_BG_WINDOW      = QColor("#000000")
_BG_BASE        = QColor("#0A0A0A")
_BG_ALT_BASE    = QColor("#141414")
_BG_BUTTON      = QColor("#171717")
_BG_TOOLTIP     = QColor("#101010")
_FG_TEXT        = QColor("#F2F2F2")
_FG_DISABLED    = QColor("#737373")
_ACCENT         = QColor("#0B5664")
_ACCENT_TEXT    = QColor("#FFFFFF")
_LINK           = QColor("#45D9F2")


def build_dark_palette() -> QPalette:
    p = QPalette()

    p.setColor(QPalette.ColorRole.Window,          _BG_WINDOW)
    p.setColor(QPalette.ColorRole.WindowText,      _FG_TEXT)
    p.setColor(QPalette.ColorRole.Base,            _BG_BASE)
    p.setColor(QPalette.ColorRole.AlternateBase,   _BG_ALT_BASE)
    p.setColor(QPalette.ColorRole.Text,            _FG_TEXT)
    p.setColor(QPalette.ColorRole.Button,          _BG_BUTTON)
    p.setColor(QPalette.ColorRole.ButtonText,      _FG_TEXT)
    p.setColor(QPalette.ColorRole.BrightText,      QColor("#FF5C5C"))
    p.setColor(QPalette.ColorRole.ToolTipBase,     _BG_TOOLTIP)
    p.setColor(QPalette.ColorRole.ToolTipText,     _FG_TEXT)
    p.setColor(QPalette.ColorRole.Highlight,       _ACCENT)
    p.setColor(QPalette.ColorRole.HighlightedText, _ACCENT_TEXT)
    p.setColor(QPalette.ColorRole.Link,            _LINK)
    p.setColor(QPalette.ColorRole.LinkVisited,     _LINK)
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor("#8A8A8A"))

    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        p.setColor(QPalette.ColorGroup.Disabled, role, _FG_DISABLED)

    # Inactive == the group used when a window loses focus. Left unset, a
    # floating dock that is not the active window reverts to system colours.
    for role, colour in (
        (QPalette.ColorRole.Window,     _BG_WINDOW),
        (QPalette.ColorRole.WindowText, _FG_TEXT),
        (QPalette.ColorRole.Base,       _BG_BASE),
        (QPalette.ColorRole.Text,       _FG_TEXT),
        (QPalette.ColorRole.Button,     _BG_BUTTON),
        (QPalette.ColorRole.ButtonText, _FG_TEXT),
    ):
        p.setColor(QPalette.ColorGroup.Inactive, role, colour)

    return p


def install_dark_palette() -> None:
    """Apply Fusion + dark palette process-wide. Safe to call more than once."""
    app = QApplication.instance()
    if app is None:
        return
    # Fusion is fully palette-driven. The native Windows/macOS styles ignore
    # large parts of the palette, which is why floating docks stay light.
    app.setStyle("Fusion")
    app.setPalette(build_dark_palette())


# --------------------------------------------------------------------------
# QSS additions
# --------------------------------------------------------------------------
DOCK_QSS_PATCH = """
/* ------------------------------------------------------------------ *
 * Dock shells - docked and floating render identically               *
 * ------------------------------------------------------------------ */
QDockWidget {
    background-color: #000000;
    color: #F2F2F2;
    font-weight: 600;
    border: none;
}
/* Native title strip is replaced by DockTitleBar; collapse the remnant. */
QDockWidget::title {
    height: 0px;
    padding: 0px;
    margin: 0px;
    background: #090909;
}
QDockWidget::close-button, QDockWidget::float-button {
    width: 0px;
    height: 0px;
    border: none;
    background: transparent;
}

QWidget#DockShell {
    background-color: #000000;
    border: 1px solid #363636;
}
QWidget#DockBody {
    background-color: #000000;
}

QWidget#DockTitleBar {
    background-color: #090909;
    border-bottom: 1px solid #363636;
}
QLabel#DockTitleLabel {
    background: transparent;
    color: #E6E6E6;
    font-size: 8.5pt;
    font-weight: 700;
    letter-spacing: 1px;
}
QPushButton#DockFloatButton, QPushButton#DockCloseButton {
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 0px;
    margin: 0px;
    color: #9A9A9A;
    font-size: 10pt;
    font-weight: 700;
}
QPushButton#DockFloatButton:hover {
    background: #1C1C1C;
    color: #8DEEFF;
    border: none;
}
QPushButton#DockCloseButton:hover {
    background: #6E1F1F;
    color: #FFDADA;
    border: none;
}

/* ------------------------------------------------------------------ *
 * Spin buttons - only reachable on widgets that keep ButtonSymbols    *
 * (Span, Reference). Center freq and Gain set NoButtons in gui.py.    *
 * ------------------------------------------------------------------ */
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    width: 18px;
    background-color: #161616;
    border-left: 1px solid #484848;
}
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-position: top right;
    border-top-right-radius: 6px;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-position: bottom right;
    border-bottom-right-radius: 6px;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: #23282B;
}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {
    background-color: #0B353C;
}
/* Geometry only - no image override, so Fusion keeps drawing the arrow
   from QPalette::ButtonText, which the dark palette now sets to #F2F2F2. */
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow,
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    width: 8px;
    height: 8px;
}
QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled,
QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled {
    width: 8px;
    height: 8px;
}

/* Scrollbars inside floating docks (palette alone leaves these grey). */
QScrollBar:vertical {
    background: #0A0A0A;
    width: 10px;
    margin: 0px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #2E2E2E;
    min-height: 28px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover { background: #45D9F2; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""