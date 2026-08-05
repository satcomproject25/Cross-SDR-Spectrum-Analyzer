"""
dock_titlebar.py
----------------
Custom title bar for QDockWidget.

Why this exists
---------------
Qt reserves the dock title height from font metrics plus
QStyle::PM_DockWidgetTitleMargin. A style sheet `QDockWidget::title { padding }`
rule changes only the *painted* rect, never the *reserved* rect, so the two
disagree. Docked, the dock separator masks it. Floating, Qt injects the
float/close buttons into the same rect and the mismatch surfaces as an
off-baseline, asymmetrically padded header.

setTitleBarWidget() removes Qt's title layout from the equation entirely: the
header becomes an ordinary widget with a fixed height and a QHBoxLayout, so it
is pixel-identical in both states and fully style-sheet addressable.

Drag-to-undock
--------------
QDockWidget implements undock-dragging in its own mouseMoveEvent. A child
title bar that accepts mouse events swallows them and undocking dies. So when
docked, this widget explicitly ignore()s presses/moves and lets them propagate
to the parent QDockWidget. When floating, it handles the drag itself so the
panel can be moved by its header.

Owner: Developer B (Frontend/GUI)
"""

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QDockWidget, QSizePolicy
)


class DockTitleBar(QWidget):
    """Fixed-height header for a QDockWidget. Styled via #DockTitleBar."""

    HEIGHT = 34
    BUTTON = 22

    def __init__(self, dock: QDockWidget, title: str):
        super().__init__(dock)
        self._dock = dock
        self._drag_offset: QPoint | None = None

        self.setObjectName("DockTitleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 6, 0)
        layout.setSpacing(4)

        self._label = QLabel(title.upper())
        self._label.setObjectName("DockTitleLabel")
        layout.addWidget(self._label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)

        self._btn_float = self._make_button("DockFloatButton", "\u25A2", "Undock / re-dock panel")
        self._btn_close = self._make_button("DockCloseButton", "\u2715", "Hide panel")
        layout.addWidget(self._btn_float, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._btn_close, 0, Qt.AlignmentFlag.AlignVCenter)

        self._btn_float.clicked.connect(self._toggle_float)
        self._btn_close.clicked.connect(self._dock.close)

        dock.topLevelChanged.connect(self._on_top_level_changed)
        self._on_top_level_changed(dock.isFloating())

    # ------------------------------------------------------------------
    def _make_button(self, object_name: str, glyph: str, tip: str) -> QPushButton:
        btn = QPushButton(glyph, self)
        btn.setObjectName(object_name)
        btn.setFixedSize(self.BUTTON, self.BUTTON)
        btn.setFlat(True)
        btn.setCursor(Qt.CursorShape.ArrowCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setToolTip(tip)
        return btn

    def set_title(self, title: str) -> None:
        self._label.setText(title.upper())

    # ------------------------------------------------------------------
    def _toggle_float(self):
        self._dock.setFloating(not self._dock.isFloating())

    def _on_top_level_changed(self, floating: bool):
        self._btn_float.setToolTip("Re-dock panel" if floating else "Undock panel")
        self._btn_float.setText("\u25A3" if floating else "\u25A2")
        # Restyle so :hover/:checked state pixmaps regenerate after reparenting.
        self.style().unpolish(self)
        self.style().polish(self)

    # ------------------------------------------------------------------
    # Mouse handling: own the drag only while floating.
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        if self._dock.isFloating():
            self._drag_offset = (
                event.globalPosition().toPoint()
                - self._dock.frameGeometry().topLeft()
            )
            event.accept()
        else:
            self._drag_offset = None
            event.ignore()          # -> QDockWidget starts the undock drag

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and self._dock.isFloating():
            self._dock.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        event.ignore()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_float()
            event.accept()
        else:
            event.ignore()


# ----------------------------------------------------------------------
def attach_dock_titlebar(dock: QDockWidget, title: str) -> DockTitleBar:
    """Install a DockTitleBar on `dock` and return it.

    The dock's windowTitle is kept in sync so QMainWindow context menus and
    the taskbar entry for a floating panel still show a sensible name.
    """
    dock.setWindowTitle(title)
    bar = DockTitleBar(dock, title)
    dock.setTitleBarWidget(bar)
    return bar


def wrap_dock_content(widget: QWidget, margin: int = 0) -> QWidget:
    """Wrap a dock's content widget in a styled shell.

    A bare QWidget has no background of its own; it inherits whatever the
    top-level surface provides. Giving it #DockShell + WA_StyledBackground
    makes the QSS background authoritative in both docked and floating state.
    """
    shell = QWidget()
    shell.setObjectName("DockShell")
    shell.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    layout = QHBoxLayout(shell)
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.setSpacing(0)
    layout.addWidget(widget)
    return shell