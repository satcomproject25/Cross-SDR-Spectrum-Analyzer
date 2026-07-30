"""
logger_panel.py
---------------
GUI dialogs for the amplitude logging feature:
  - LoggerSetupDialog: enter any number of carrier frequencies (start with 2
    rows, "+" adds more), each validated against the live span, then starts
    a logging session.
  - LoggerPlotDialog: browse Year -> Month -> Day and plot a day's logged
    amplitude columns vs time. Thin vertical red lines mark where one
    logging session ended and another began within that day's file.

Owner: Developer B (Frontend/GUI)
"""

from __future__ import annotations

from pathlib import Path

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from backend.amplitude_logger import AmplitudeLogger, LoggerValidationError, validate_frequency_in_span

# Colors matched to frontend/gui.py's _apply_dark_theme() palette.
COLOR_BACKGROUND = "#000000"
COLOR_PANEL = "#0A0A0A"
COLOR_BORDER = "#484848"
COLOR_TEXT = "#F2F2F2"
COLOR_MUTED_TEXT = "#B8B8B8"
COLOR_AXIS_TEXT = "#CCCCCC"
COLOR_ACCENT = "#33D6EE"
COLOR_ACCENT_TEXT = "#8DEEFF"
COLOR_ERROR = "#FF6B6B"
COLOR_SESSION_LINE = "#E23636"

# Cycled across however many frequencies are tracked in a session.
TRACE_COLORS = [
    "#00F0FF", "#FF7F00", "#B45CFF", "#FFD60A", "#5FD791", "#FF4FD8",
]

DIALOG_STYLESHEET = f"""
    QDialog {{
        background-color: {COLOR_BACKGROUND};
    }}
    QWidget {{
        color: {COLOR_TEXT};
        font-family: "Segoe UI", Arial, sans-serif;
        font-size: 10pt;
    }}
    QLabel {{
        color: {COLOR_TEXT};
        background: transparent;
    }}
    QLabel#DialogInfo {{
        color: {COLOR_MUTED_TEXT};
    }}
    QLabel#RowError {{
        color: {COLOR_ERROR};
    }}
    QPushButton {{
        background-color: #171717;
        border: 1px solid {COLOR_BORDER};
        padding: 8px 13px;
        border-radius: 6px;
        font-weight: 600;
    }}
    QPushButton:hover {{ background-color: #262626; border-color: {COLOR_ACCENT}; }}
    QPushButton:pressed {{ background-color: #0F0F0F; }}
    QPushButton#AddFrequencyButton {{
        background: #0B353C;
        border-color: {COLOR_ACCENT};
        color: {COLOR_ACCENT_TEXT};
        font-weight: 700;
        max-width: 34px;
    }}
    QPushButton#RemoveFrequencyButton {{
        background: #2A1414;
        border-color: #7A2E2E;
        color: #FFB3B3;
        max-width: 34px;
    }}
    QPushButton#OkButton {{
        background: #0F4C3A;
        border-color: #1B7A5C;
        color: #8FF0C7;
    }}
    QDoubleSpinBox, QComboBox {{
        background-color: #111111;
        border: 1px solid {COLOR_BORDER};
        padding: 7px 9px;
        border-radius: 6px;
        selection-background-color: #0B5664;
    }}
    QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {COLOR_ACCENT}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background-color: #101010;
        color: {COLOR_TEXT};
        border: 1px solid {COLOR_BORDER};
        selection-background-color: #0B5664;
        selection-color: #FFFFFF;
    }}
    QFrame#FrequencyRow {{
        background-color: {COLOR_PANEL};
        border: 1px solid #363636;
        border-radius: 8px;
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
"""


class _FrequencyRow(QWidget):
    """One 'Frequency N: [____] MHz  [-]' row inside the setup dialog."""

    def __init__(self, index: int, initial_mhz: float, removable: bool, parent=None):
        super().__init__(parent)
        self.index = index

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.label = QLabel(f"Frequency {index + 1}:")
        self.label.setMinimumWidth(90)

        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(6)
        self.spin.setRange(0.0, 6000.0)
        self.spin.setSuffix(" MHz")
        self.spin.setValue(initial_mhz)
        self.spin.setMinimumWidth(160)

        self.remove_button = QPushButton("\u2212")  # minus sign
        self.remove_button.setObjectName("RemoveFrequencyButton")
        self.remove_button.setFixedWidth(34)
        self.remove_button.setVisible(removable)

        layout.addWidget(self.label)
        layout.addWidget(self.spin, 1)
        layout.addWidget(self.remove_button)

    def set_index(self, index: int):
        self.index = index
        self.label.setText(f"Frequency {index + 1}:")

    def frequency_hz(self) -> float:
        return self.spin.value() * 1e6


class LoggerSetupDialog(QDialog):
    """Modal dialog to collect any number of frequencies to log.

    Starts with 2 rows; "+" adds more, "-" removes a row (down to a minimum
    of 1). Every frequency is validated against the current span before OK
    is accepted.
    """

    def __init__(self, center_frequency_hz: float, span_hz: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Amplitude Logger")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setStyleSheet(DIALOG_STYLESHEET)
        self._center_frequency_hz = center_frequency_hz
        self._span_hz = span_hz
        self._result_frequencies: list[float] | None = None
        self._rows: list[_FrequencyRow] = []

        outer_layout = QVBoxLayout(self)
        outer_layout.setSpacing(12)

        lower_mhz = (center_frequency_hz - span_hz / 2) / 1e6
        upper_mhz = (center_frequency_hz + span_hz / 2) / 1e6
        info = QLabel(
            "Track any number of carrier center frequencies, all within the\n"
            f"current span ({lower_mhz:.6f} - {upper_mhz:.6f} MHz)."
        )
        info.setObjectName("DialogInfo")
        info.setWordWrap(True)
        outer_layout.addWidget(info)

        # Rows live in a scrollable area so an arbitrary number of "+" adds
        # doesn't grow the dialog off-screen.
        self.rows_container = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.rows_container)
        scroll.setMaximumHeight(260)
        outer_layout.addWidget(scroll)

        add_row_layout = QHBoxLayout()
        self.add_button = QPushButton("+  Add frequency")
        self.add_button.setObjectName("AddFrequencyButton")
        self.add_button.setMaximumWidth(160)
        add_row_layout.addWidget(self.add_button)
        add_row_layout.addStretch(1)
        outer_layout.addLayout(add_row_layout)

        self.error_label = QLabel("")
        self.error_label.setObjectName("RowError")
        self.error_label.setWordWrap(True)
        outer_layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.ok_button.setObjectName("OkButton")
        self.cancel_button = QPushButton("Cancel")
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.ok_button)
        outer_layout.addLayout(buttons)

        self.add_button.clicked.connect(self._add_row)
        self.ok_button.clicked.connect(self._on_ok)
        self.cancel_button.clicked.connect(self.reject)

        # Start with 2 rows, as before, but now backed by the same
        # add/remove machinery as every later row.
        self._add_row(initial_mhz=center_frequency_hz / 1e6)
        self._add_row(initial_mhz=0.0)

    def _add_row(self, initial_mhz: float = 0.0):
        row = _FrequencyRow(
            index=len(self._rows), initial_mhz=initial_mhz, removable=True, parent=self.rows_container
        )
        row.remove_button.clicked.connect(lambda: self._remove_row(row))
        self._rows.append(row)
        self.rows_layout.addWidget(row)
        self._sync_remove_visibility()

    def _remove_row(self, row: _FrequencyRow):
        if len(self._rows) <= 1:
            return
        self._rows.remove(row)
        self.rows_layout.removeWidget(row)
        row.deleteLater()
        for index, remaining_row in enumerate(self._rows):
            remaining_row.set_index(index)
        self._sync_remove_visibility()

    def _sync_remove_visibility(self):
        only_row = len(self._rows) == 1
        for row in self._rows:
            row.remove_button.setVisible(not only_row)

    def _on_ok(self):
        frequencies_hz = [row.frequency_hz() for row in self._rows if row.frequency_hz() > 0.0]
        if not frequencies_hz:
            self.error_label.setText("Enter at least one frequency greater than 0 MHz.")
            return

        try:
            for freq in frequencies_hz:
                validate_frequency_in_span(
                    freq, self._center_frequency_hz, self._span_hz
                )
        except LoggerValidationError as exc:
            self.error_label.setText(str(exc))
            return

        self._result_frequencies = frequencies_hz
        self.accept()

    def result_frequencies_hz(self) -> list[float] | None:
        return self._result_frequencies


class LoggerPlotDialog(QDialog):
    """Browse Year/Month/Day and plot that day's logged amplitude columns.

    Since logging now writes one CSV per calendar day (every start/stop
    session in a day appends to the same file), there is no separate
    "session" selector -- picking a day plots its entire file, with thin
    vertical red lines marking where each individual session began.
    """

    def __init__(self, logger: AmplitudeLogger, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Amplitude Logger - Plot Recorded Day")
        self.setStyleSheet(DIALOG_STYLESHEET)
        self.resize(900, 560)
        self._logger = logger

        layout = QVBoxLayout(self)

        selector_row = QHBoxLayout()
        self.year_combo = QComboBox()
        self.month_combo = QComboBox()
        self.day_combo = QComboBox()
        for label, combo in (
            ("Year", self.year_combo),
            ("Month", self.month_combo),
            ("Day", self.day_combo),
        ):
            selector_row.addWidget(QLabel(label + ":"))
            selector_row.addWidget(combo)
        self.plot_button = QPushButton("Plot")
        selector_row.addWidget(self.plot_button)
        selector_row.addStretch(1)
        layout.addLayout(selector_row)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground(COLOR_BACKGROUND)
        plot_item = self.plot_widget.getPlotItem()
        plot_item.setLabel("bottom", "Time (HH:MM:SS)", color=COLOR_AXIS_TEXT)
        plot_item.setLabel("left", "Amplitude", color=COLOR_AXIS_TEXT)
        for axis_name in ("bottom", "left"):
            axis = plot_item.getAxis(axis_name)
            axis.setTextPen(COLOR_AXIS_TEXT)
        layout.addWidget(self.plot_widget, 1)

        self.year_combo.currentTextChanged.connect(self._on_year_changed)
        self.month_combo.currentTextChanged.connect(self._on_month_changed)
        self.plot_button.clicked.connect(self._on_plot)

        self._populate_years()

    def _populate_years(self):
        self.year_combo.blockSignals(True)
        self.year_combo.clear()
        self.year_combo.addItems(self._logger.available_years())
        self.year_combo.blockSignals(False)
        self._on_year_changed(self.year_combo.currentText())

    def _on_year_changed(self, year: str):
        self.month_combo.blockSignals(True)
        self.month_combo.clear()
        if year:
            self.month_combo.addItems(self._logger.available_months(year))
        self.month_combo.blockSignals(False)
        self._on_month_changed(self.month_combo.currentText())

    def _on_month_changed(self, month: str):
        self.day_combo.blockSignals(True)
        self.day_combo.clear()
        year = self.year_combo.currentText()
        if year and month:
            self.day_combo.addItems(self._logger.available_days(year, month))
        self.day_combo.blockSignals(False)

    def _on_plot(self):
        year = self.year_combo.currentText()
        month = self.month_combo.currentText()
        day = self.day_combo.currentText()
        if not (year and month and day):
            QMessageBox.information(self, "No day selected", "Choose a Year/Month/Day first.")
            return

        path = self._logger.day_file(year, month, day)
        if path is None:
            QMessageBox.information(self, "No recording found", "No log file exists for that day.")
            return

        try:
            timestamps, freq_labels, columns, session_boundaries = AmplitudeLogger.read_day_file(path)
        except (OSError, StopIteration) as exc:
            QMessageBox.warning(self, "Could not read log file", str(exc))
            return

        self.plot_widget.clear()
        plot_item = self.plot_widget.getPlotItem()
        plot_item.addLegend()

        x_values = list(range(len(timestamps)))
        for i, (label, values) in enumerate(zip(freq_labels, columns)):
            color = TRACE_COLORS[i % len(TRACE_COLORS)]
            self.plot_widget.plot(
                x_values, values, pen=pg.mkPen(color=color, width=1.6), name=label
            )

        # Thin vertical red lines mark each session boundary within the day.
        # The very first session's boundary (row 0) is skipped -- there is
        # nothing to differentiate it from, and it would just sit on the
        # plot's left edge.
        for boundary_index in session_boundaries:
            if boundary_index == 0:
                continue
            line = pg.InfiniteLine(
                pos=boundary_index,
                angle=90,
                pen=pg.mkPen(color=COLOR_SESSION_LINE, width=1, style=Qt.PenStyle.SolidLine),
            )
            line.setZValue(-1)
            self.plot_widget.addItem(line)

        axis = plot_item.getAxis("bottom")
        tick_step = max(1, len(timestamps) // 12)
        ticks = [(i, timestamps[i]) for i in range(0, len(timestamps), tick_step)]
        axis.setTicks([ticks])