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

    option_selected = pyqtSignal(int)   # emits 0 for None or marker IDs 1 through 6
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("MarkerDropdownPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("""
            #MarkerDropdownPanel {
                background-color: #101010;
                border: 1px solid #484848;
                border-radius: 8px;
            }
            QPushButton {
                background-color: transparent;
                color: #F2F2F2;
                border: none;
                border-radius: 0px;
                padding: 8px 24px;
                font-size: 10pt;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #262626;
            }
            QPushButton:checked {
                background-color: #0B353C;
                color: #8DEEFF;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._buttons = {}
        options = [(0, "None")] + [(i, f"Marker {i}") for i in range(1, 7)]
        for marker_id, label in options:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, mid=marker_id: self._on_option(mid))
            layout.addWidget(btn)
            self._buttons[marker_id] = btn

        self._buttons[0].setChecked(True)

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
    Signals: marker_selected(int) emits 0 for None or a marker ID from 1 through 6.
    """

    marker_selected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__("None  ▾", parent)
        self._current_id = 0
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
        self._panel.resize(170, 36 * 7)
        self._panel.show()
        self._panel_open = True

    def _on_marker_selected(self, marker_id: int):
        self._current_id = marker_id
        self.setText("None  ▾" if marker_id == 0 else f"Marker {marker_id}  ▾")
        self.marker_selected.emit(marker_id)

    def _on_panel_closed(self):
        self._panel_open = False

    def current_marker_id(self) -> int:
        return self._current_id
