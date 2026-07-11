"""
marker_dropdown.py
------------------
Persistent marker selector dropdown widget.
Stays open on hover-out. Only closes when:
  - user clicks an option
  - user clicks the button again
  - user presses Escape
Owner: Developer B (Frontend/GUI)
"""

from PyQt6.QtCore import Qt, pyqtSignal, QPoint
from PyQt6.QtWidgets import (
    QWidget, QPushButton, QVBoxLayout, QFrame,
    QApplication, QLabel
)
from PyQt6.QtGui import QKeyEvent


class _DropdownPanel(QFrame):
    """The popup panel. Frameless window that stays on screen until dismissed."""

    option_selected = pyqtSignal(int)   # emits 1 / 2 / 3
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("MarkerDropdownPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("""
            #MarkerDropdownPanel {
                background-color: #2B2B2B;
                border: 1px solid #4A4A4A;
            }
            QPushButton {
                background-color: transparent;
                color: #E0E0E0;
                border: none;
                border-radius: 0px;
                padding: 8px 24px;
                font-size: 10pt;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #3A3A3A;
            }
            QPushButton:checked {
                background-color: #505050;
                color: #FFFFFF;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._buttons = {}
        for i, label in enumerate(["Marker 1", "Marker 2", "Marker 3"], start=1):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, mid=i: self._on_option(mid))
            layout.addWidget(btn)
            self._buttons[i] = btn

        self._buttons[1].setChecked(True)

    def _on_option(self, marker_id: int):
        for mid, btn in self._buttons.items():
            btn.setChecked(mid == marker_id)
        self.option_selected.emit(marker_id)
        # Do NOT close here — stays open until button re-click or Escape

    def set_selected(self, marker_id: int):
        for mid, btn in self._buttons.items():
            btn.setChecked(mid == marker_id)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            self.closed.emit()
        else:
            super().keyPressEvent(event)

    # Override mousePressEvent so clicking OUTSIDE the panel (Qt.Popup behavior)
    # hides it — but hover-out does nothing
    def hideEvent(self, event):
        self.closed.emit()
        super().hideEvent(event)


class MarkerSelectorButton(QPushButton):
    """
    Drop-in replacement for the marker QComboBox.
    Shows persistent popup — hover-out does NOT close it.
    Signals: marker_selected(int) emits 1, 2, or 3.
    """

    marker_selected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__("Marker 1  ▾", parent)
        self._current_id = 1
        self._panel = _DropdownPanel()
        self._panel.option_selected.connect(self._on_marker_selected)
        self._panel.closed.connect(self._on_panel_closed)
        self._panel_open = False
        self.clicked.connect(self._toggle_panel)

    def _toggle_panel(self):
        if self._panel_open:
            self._panel.hide()
            # _on_panel_closed handles state
        else:
            self._open_panel()

    def _open_panel(self):
        # Position the panel directly below this button
        btn_bottom_left = self.mapToGlobal(QPoint(0, self.height()))
        self._panel.move(btn_bottom_left)
        self._panel.resize(160, 33 * 3)
        self._panel.show()
        self._panel_open = True

    def _on_marker_selected(self, marker_id: int):
        self._current_id = marker_id
        self.setText(f"Marker {marker_id}  ▾")
        self.marker_selected.emit(marker_id)

    def _on_panel_closed(self):
        self._panel_open = False

    def current_marker_id(self) -> int:
        return self._current_id