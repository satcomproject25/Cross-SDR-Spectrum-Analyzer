"""
logger_panel.py
---------------
GUI dialogs for the amplitude logging feature:
  - LoggerSetupDialog: enter up to 2 carrier frequencies, validated against
    the live span, then starts a logging session.
  - LoggerPlotDialog: browse Year -> Month -> Day -> session CSV and plot
    amplitude vs time for every logged frequency column.

Owner: Developer B (Frontend/GUI)
"""

from __future__ import annotations

from pathlib import Path

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QVBoxLayout,
)

from backend.amplitude_logger import AmplitudeLogger, LoggerValidationError, validate_frequency_in_span

COLOR_BACKGROUND = "#000000"
COLOR_AXIS_TEXT = "#CCCCCC"
TRACE_COLORS = ["#00F0FF", "#FF7F00"]  # up to 2 tracked frequencies


class LoggerSetupDialog(QDialog):
    """Modal dialog to collect 1-2 frequencies to log, validated against span."""

    def __init__(self, center_frequency_hz: float, span_hz: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Amplitude Logger")
        self.setModal(True)
        self._center_frequency_hz = center_frequency_hz
        self._span_hz = span_hz
        self._result_frequencies: list[float] | None = None

        layout = QVBoxLayout(self)

        info = QLabel(
            f"Enter up to 2 carrier center frequencies within the current span\n"
            f"({(center_frequency_hz - span_hz / 2) / 1e6:.6f} - "
            f"{(center_frequency_hz + span_hz / 2) / 1e6:.6f} MHz)."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self.freq1_spin = QDoubleSpinBox()
        self.freq1_spin.setDecimals(6)
        self.freq1_spin.setRange(0.0, 6000.0)
        self.freq1_spin.setSuffix(" MHz")
        self.freq1_spin.setValue(center_frequency_hz / 1e6)

        self.freq2_spin = QDoubleSpinBox()
        self.freq2_spin.setDecimals(6)
        self.freq2_spin.setRange(0.0, 6000.0)
        self.freq2_spin.setSuffix(" MHz")
        self.freq2_spin.setSpecialValueText("(unused)")
        self.freq2_spin.setValue(0.0)

        form.addRow("Frequency 1:", self.freq1_spin)
        form.addRow("Frequency 2 (optional):", self.freq2_spin)
        layout.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #FF6B6B;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.cancel_button = QPushButton("Cancel")
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.ok_button)
        layout.addLayout(buttons)

        self.ok_button.clicked.connect(self._on_ok)
        self.cancel_button.clicked.connect(self.reject)

    def _on_ok(self):
        frequencies_hz = [self.freq1_spin.value() * 1e6]
        if self.freq2_spin.value() > 0.0:
            frequencies_hz.append(self.freq2_spin.value() * 1e6)

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
    """Browse Year/Month/Day and plot a session's logged amplitude columns."""

    def __init__(self, logger: AmplitudeLogger, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Amplitude Logger - Plot Recorded Session")
        self.resize(900, 560)
        self._logger = logger

        layout = QVBoxLayout(self)

        selector_row = QHBoxLayout()
        self.year_combo = QComboBox()
        self.month_combo = QComboBox()
        self.day_combo = QComboBox()
        self.session_combo = QComboBox()
        for label, combo in (
            ("Year", self.year_combo),
            ("Month", self.month_combo),
            ("Day", self.day_combo),
            ("Session", self.session_combo),
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
        plot_item.addLegend()
        for axis_name in ("bottom", "left"):
            axis = plot_item.getAxis(axis_name)
            axis.setTextPen(COLOR_AXIS_TEXT)
        layout.addWidget(self.plot_widget, 1)

        self.year_combo.currentTextChanged.connect(self._on_year_changed)
        self.month_combo.currentTextChanged.connect(self._on_month_changed)
        self.day_combo.currentTextChanged.connect(self._on_day_changed)
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
        self._on_day_changed(self.day_combo.currentText())

    def _on_day_changed(self, day: str):
        self.session_combo.clear()
        year = self.year_combo.currentText()
        month = self.month_combo.currentText()
        if year and month and day:
            sessions = self._logger.sessions_for_day(year, month, day)
            for path in sessions:
                self.session_combo.addItem(path.name, str(path))

    def _on_plot(self):
        path_str = self.session_combo.currentData()
        if not path_str:
            QMessageBox.information(self, "No session selected", "Choose a Year/Month/Day/Session first.")
            return
        try:
            timestamps, freq_labels, columns = AmplitudeLogger.read_session(Path(path_str))
        except (OSError, StopIteration) as exc:
            QMessageBox.warning(self, "Could not read session", str(exc))
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

        axis = plot_item.getAxis("bottom")
        tick_step = max(1, len(timestamps) // 12)
        ticks = [(i, timestamps[i]) for i in range(0, len(timestamps), tick_step)]
        axis.setTicks([ticks])